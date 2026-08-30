from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo

import discord

from app.domain.public_cards import (
    ActivePublicTrade,
    DailyActiveTrade,
    DailyCategorySummary,
    DailyClosedTrade,
    PublicAnalysisCard,
    PublicTradeCard,
)
from app.services.analysis_pipeline import AnalysisDraftSnapshot
from app.services.card_review import ReviewDraft, publication_missing_fields
from app.services.official_results import OfficialResult

ACCENT_GREEN = 0x86F7A8
MUTED = 0x9A9F9B
DANGER = 0xD66A6A

ACTION_LABELS = {
    "ENTRY": "入场",
    "UPDATE": "订单更新",
    "TP1": "止盈一",
    "TP2": "止盈二",
    "RUNNER": "保留尾仓",
    "PARTIAL_SL": "部分触发 SL",
    "SL": "触发 SL",
    "CLOSE": "全部平仓",
    "CANCEL": "取消订单",
    "ROLL": "滚仓",
    "ADD_FIRST": "第一次加仓",
    "ADD_SECOND": "第二次加仓",
    "ADD_THIRD": "第三次加仓",
    "ADD_FOURTH": "特殊第四次加仓",
}
STAGE_LABELS = {
    "FIRST": "第一次加仓",
    "SECOND": "第二次加仓",
    "THIRD": "第三次加仓",
    "FOURTH": "特殊第四次加仓",
}
CATEGORY_LABELS = {
    "SHORT_TERM": "短线",
    "SWING": "波段",
    "LEAPS": "长期",
}


def action_label(draft: ReviewDraft | PublicTradeCard) -> str:
    if draft.action == "ADD":
        return STAGE_LABELS.get(draft.action_stage or "", "加仓")
    return ACTION_LABELS.get(draft.action, draft.action or "未识别")


def _number(value: Decimal | None) -> str:
    if value is None:
        return "—"
    rendered = f"{value:f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"${_number(value)}"


def _position(value: int | None) -> str:
    if value is None:
        return "—"
    if value == 8:
        return "满仓"
    if value == 0:
        return "0"
    fractions = {2: "1/4", 4: "1/2", 6: "3/4"}
    return f"{fractions.get(value, f'{value}/8')} 仓位"


def _contract(draft: ReviewDraft | PublicTradeCard) -> str:
    expiry = draft.expiry.strftime("%m/%d/%Y") if draft.expiry else "—"
    side = {"CALL": "C", "PUT": "P"}.get(draft.option_side or "", "?")
    strike = _number(draft.strike)
    return f"{draft.ticker or '—'} · {expiry} · {strike}{side}"


def build_review_embed(draft: ReviewDraft) -> discord.Embed:
    color = DANGER if draft.status == "PARSE_FAILED" else MUTED
    title = "待审核订单"
    if draft.status == "READY":
        color = ACCENT_GREEN
        title = "审核通过"
    elif draft.status == "PUBLISHED":
        color = ACCENT_GREEN
        title = "已发布"
    elif draft.status == "PUBLISH_FAILED":
        color = DANGER
        title = "发布失败 · 等待重试"
    elif draft.status == "PARSE_FAILED":
        title = "解析失败草稿"
    elif draft.status == "DELETED":
        color = DANGER
        title = "已删除草稿"
    embed = discord.Embed(
        title=f"{title} · {draft.draft_code}",
        description=f"**识别操作**\n{action_label(draft)}",
        color=color,
    )
    embed.add_field(name="合约", value=_contract(draft), inline=False)
    if draft.entry_low is not None or draft.entry_high is not None:
        embed.add_field(
            name="入场区间",
            value=f"{_money(draft.entry_low)} – {_money(draft.entry_high)}",
            inline=True,
        )
    if draft.action_price is not None:
        embed.add_field(name="本次操作价格", value=_money(draft.action_price), inline=True)
    if draft.position_delta_eighths is not None:
        embed.add_field(
            name="本次操作仓位",
            value=_position(draft.position_delta_eighths),
            inline=True,
        )
    embed.add_field(name="操作后持仓", value=_position(draft.position_after_eighths), inline=True)
    if draft.avg_cost is not None:
        embed.add_field(name="操作后平均成本", value=_money(draft.avg_cost), inline=True)
    if draft.current_pnl_pct is not None:
        embed.add_field(name="当前收益", value=f"{_number(draft.current_pnl_pct)}%", inline=True)
    for name, value in (("SL", draft.sl), ("TP1", draft.tp1), ("TP2", draft.tp2)):
        if value is not None:
            embed.add_field(name=name, value=_money(value), inline=True)
    embed.add_field(
        name="分类",
        value=(
            CATEGORY_LABELS.get(draft.selected_category or "", "尚未选择")
            + (
                "\n建议："
                + CATEGORY_LABELS.get(draft.category_suggestion, draft.category_suggestion)
                if draft.category_suggestion and not draft.selected_category
                else ""
            )
        ),
        inline=True,
    )
    embed.add_field(name="Mentor", value=draft.mentor_name or "尚未选择", inline=True)
    embed.add_field(name="对应订单", value=draft.matched_trade_code or "尚未关联", inline=True)
    missing = publication_missing_fields(draft)
    if missing:
        embed.add_field(name="发布前缺失", value="、".join(missing), inline=False)
    if draft.warnings:
        embed.add_field(name="解析警告", value="\n".join(draft.warnings)[:1024], inline=False)
    confidence = _number(draft.parser_confidence)
    embed.set_footer(
        text=f"AXIS Signal · {draft.draft_code} · v{draft.version} · confidence {confidence}"
    )
    return embed


def build_public_preview_embed(card: PublicTradeCard) -> discord.Embed:
    embed = build_public_trade_embed(card)
    embed.title = f"预览 · {action_label(card)}"
    embed.set_footer(text="管理员预览 · 尚未发布")
    return embed


def build_public_trade_embed(
    card: PublicTradeCard, *, public_ref: str | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=(
            f"{action_label(card)} · {card.public_trade_id}"
            if card.public_trade_id
            else action_label(card)
        ),
        description=_contract(card),
        color=ACCENT_GREEN,
    )
    if card.entry_low is not None or card.entry_high is not None:
        embed.add_field(
            name="入场区间",
            value=f"{_money(card.entry_low)} – {_money(card.entry_high)}",
            inline=False,
        )
    if card.action_price is not None:
        price_label = {
            "ADD": "本次加仓价格",
            "TP1": "止盈价格",
            "TP2": "止盈价格",
        }.get(card.action, "本次操作价格")
        embed.add_field(name=price_label, value=_money(card.action_price), inline=False)
    if card.position_delta_eighths is not None:
        position_label = {
            "ADD": "本次加仓",
            "TP1": "本次卖出",
            "TP2": "本次卖出",
        }.get(card.action, "本次操作仓位")
        embed.add_field(
            name=position_label,
            value=_position(abs(card.position_delta_eighths)),
            inline=True,
        )
    average_label = "加仓后平均成本" if card.action == "ADD" else "当前平均成本"
    if card.avg_cost is not None:
        embed.add_field(name=average_label, value=_money(card.avg_cost), inline=True)
    after_label = {
        "ADD": "加仓后持仓",
        "TP1": "止盈后持仓",
        "TP2": "止盈后持仓",
        "ENTRY": "当前持仓",
    }.get(card.action, "操作后持仓")
    embed.add_field(name=after_label, value=_position(card.position_after_eighths), inline=True)
    if card.pnl_pct is not None:
        pnl_label = "本次收益" if card.action in {"TP1", "TP2", "CLOSE"} else "当前收益"
        embed.add_field(name=pnl_label, value=f"{_number(card.pnl_pct)}%", inline=True)
    sl_label = "新 SL" if card.action in {"TP1", "TP2", "ADD", "UPDATE"} else "SL"
    for name, value in ((sl_label, card.sl), ("TP1", card.tp1), ("TP2", card.tp2)):
        if value is not None:
            embed.add_field(name=name, value=_money(value), inline=True)
    if public_ref:
        embed.set_footer(text=f"AXIS · {public_ref}")
    return embed


def build_active_orders_embed(category: str, trades: list[ActivePublicTrade]) -> discord.Embed:
    title = {
        "SHORT_TERM": "当前短线订单",
        "SWING": "当前波段订单",
        "LEAPS": "当前长期订单",
    }.get(category, "当前订单")
    embed = discord.Embed(title=title, color=ACCENT_GREEN)
    if not trades:
        embed.description = "当前没有进行中的订单。"
        return embed
    for trade in trades:
        expiry = trade.expiry.strftime("%m/%d")
        side = {"CALL": "C", "PUT": "P"}.get(trade.option_side, "?")
        contract = f"{trade.ticker} {expiry} {_number(trade.strike)}{side}"
        label = ACTION_LABELS.get(trade.last_public_action, trade.last_public_action)
        embed.add_field(
            name=trade.public_trade_id,
            value=f"{contract}\n{label} · 当前持仓 {_position(trade.position_eighths)}",
            inline=False,
        )
    return embed


def build_official_result_embed(result: OfficialResult) -> discord.Embed:
    side = {"CALL": "C", "PUT": "P"}.get(result.option_side, "?")
    contract = (
        f"{result.ticker} · {result.expiry.strftime('%m/%d/%Y')} · {_number(result.strike)}{side}"
    )
    value = result.final_return_pct.quantize(Decimal("0.01"))
    rendered_return = f"{value:+f}%"
    embed = discord.Embed(
        title=f"已完成 · {result.public_trade_id}",
        description=contract,
        color=ACCENT_GREEN if value >= 0 else DANGER,
    )
    embed.add_field(name="加权最终收益", value=rendered_return, inline=False)
    embed.set_footer(text=f"AXIS Result · {result.public_trade_id}")
    return embed


def _daily_contract(item: DailyActiveTrade | DailyClosedTrade) -> str:
    expiry = item.expiry.strftime("%m/%d/%Y")
    side = {"CALL": "C", "PUT": "P"}.get(item.option_side, "?")
    return f"{item.ticker} · {expiry} · {_number(item.strike)}{side}"


def build_daily_summary_embeds(summary: DailyCategorySummary) -> list[discord.Embed]:
    category = CATEGORY_LABELS.get(summary.category, summary.category)
    date_label = summary.session_date.strftime("%Y/%m/%d")
    active = discord.Embed(
        title=f"{category} · Active 收盘总结",
        color=ACCENT_GREEN,
    )
    if not summary.active:
        active.description = "当前没有进行中的订单。"
    else:
        lines = []
        for trade in summary.active[:15]:
            if trade.reference_price is None:
                quote = "行情暂不可用"
            else:
                quote = f"当前/收盘参考价 {_money(trade.reference_price)}"
                if trade.unrealized_pnl_pct is not None:
                    quote += f" · 浮动 {trade.unrealized_pnl_pct:+.2f}%"
                if trade.quote_time is not None:
                    et_time = trade.quote_time.astimezone(ZoneInfo("America/New_York"))
                    quote += f" · {et_time:%m/%d %H:%M} ET"
            lines.append(
                f"**{trade.public_trade_id}** · {_daily_contract(trade)}\n"
                f"{_position(trade.position_eighths)} · 成本 {_money(trade.avg_cost)} · {quote}"
            )
        if len(summary.active) > 15:
            remaining = len(summary.active) - 15
            lines.append(f"另有 {remaining} 个 Active 订单，请使用「查看当前订单」。")
        active.description = "\n\n".join(lines)

    closed = discord.Embed(
        title=f"{category} · 今日 Closed 总结",
        color=MUTED,
    )
    if not summary.closed:
        closed.description = "今日没有已完成订单。"
    else:
        lines = []
        for trade in summary.closed[:15]:
            result = (
                "加权最终收益待确认"
                if trade.final_return_pct is None
                else f"加权最终收益 {trade.final_return_pct:+.2f}%"
            )
            lines.append(f"**{trade.public_trade_id}** · {_daily_contract(trade)}\n{result}")
        if len(summary.closed) > 15:
            lines.append(f"另有 {len(summary.closed) - 15} 个今日 Closed 订单。")
        closed.description = "\n\n".join(lines)

    footer = f"AXIS · {date_label} ET · 只读行情参考"
    active.set_footer(text=footer)
    closed.set_footer(text=footer)
    return [active, closed]


def build_analysis_review_embed(
    draft: AnalysisDraftSnapshot, *, image_filename: str | None = None
) -> discord.Embed:
    payload = draft.normalized
    type_label = {
        "MARKET": "市场观察",
        "TICKER": "标的观察",
        "SECTOR": "板块观察",
        "MACRO": "宏观观察",
        "UNKNOWN": "待识别观点",
    }.get(str(payload.get("analysis_type")), "待识别观点")
    embed = discord.Embed(
        title=f"{type_label} · {draft.draft_code}",
        description=str(payload.get("title") or payload.get("summary") or "需要人工整理"),
        color=DANGER if draft.status == "PARSE_FAILED" else MUTED,
    )
    embed.add_field(
        name="标的",
        value=", ".join(payload.get("symbols", [])) or payload.get("sector") or "—",
        inline=True,
    )
    embed.add_field(name="方向", value=str(payload.get("stance", "WATCH")), inline=True)
    embed.add_field(
        name="观察周期", value=str(payload.get("time_horizon", "UNSPECIFIED")), inline=True
    )
    embed.add_field(name="Mentor", value=draft.mentor_name or "尚未选择", inline=False)
    if payload.get("core_thesis"):
        embed.add_field(name="核心观点", value=str(payload["core_thesis"])[:1024], inline=False)
    if payload.get("why_now"):
        embed.add_field(
            name="为什么现在关注",
            value="\n".join(f"• {item}" for item in payload["why_now"])[:1024],
            inline=False,
        )
    if payload.get("supporting_points"):
        embed.add_field(
            name="综合依据",
            value="\n".join(f"• {item}" for item in payload["supporting_points"])[:1024],
            inline=False,
        )
    if payload.get("engine_observations"):
        embed.add_field(
            name="AXIS 结构观察",
            value="\n".join(f"• {item}" for item in payload["engine_observations"])[:1024],
            inline=False,
        )
    levels = []
    for level in payload.get("key_levels", []):
        if not isinstance(level, dict):
            continue
        price = level.get("price")
        note = level.get("note")
        if price is not None or note:
            levels.append(
                f"{level.get('level_type', 'WATCH')}: "
                f"{price if price is not None else ''} {note or ''}".strip()
            )
    if levels:
        embed.add_field(name="路径与关键位", value="\n".join(levels)[:1024], inline=False)
    projection = payload.get("source_projection")
    route = projection.get("path_points") if isinstance(projection, dict) else None
    if isinstance(route, list) and route:
        route_lines = []
        for index, point in enumerate(route[:12], start=1):
            if not isinstance(point, dict):
                continue
            price = point.get("price")
            route_lines.append(
                f"P{index} · {point.get('direction', 'FLAT')}"
                + (f" · ${float(price):,.2f}" if isinstance(price, (int, float)) else "")
                + (f" · {point['label']}" if point.get("label") else "")
            )
        if route_lines:
            embed.add_field(
                name="预测路径（文字）",
                value=" → \n".join(route_lines)[:1024],
                inline=False,
            )
    if payload.get("invalidation"):
        embed.add_field(name="失效条件", value=str(payload["invalidation"])[:1024], inline=False)
    if draft.warnings:
        embed.add_field(name="Warnings", value="\n".join(draft.warnings)[:1024], inline=False)
    if image_filename:
        embed.set_image(url=f"attachment://{image_filename}")
    embed.set_footer(
        text=f"AXIS Analysis · {draft.draft_code} · r{draft.revision} · v{draft.version}"
    )
    return embed


def build_public_analysis_embed(
    card: PublicAnalysisCard,
    *,
    public_ref: str,
    image_filename: str | None = None,
) -> discord.Embed:
    type_label = {
        "MARKET": "市场观察",
        "TICKER": "标的观察",
        "SECTOR": "板块观察",
        "MACRO": "宏观观察",
    }[card.analysis_type]
    subject = ", ".join(card.symbols) or card.sector or card.analysis_code
    stance = {
        "BULLISH": "偏多",
        "BEARISH": "偏空",
        "NEUTRAL": "中性",
        "WATCH": "观察",
    }[card.stance]
    horizon = {
        "INTRADAY": "日内",
        "SHORT_TERM": "短线",
        "SWING": "波段",
        "LONG_TERM": "长期",
        "UNSPECIFIED": "未指定",
    }[card.time_horizon]
    embed = discord.Embed(
        title=f"{type_label} · {subject}",
        description=card.title or card.summary,
        color=ACCENT_GREEN,
    )
    embed.add_field(name="当前观点", value=stance, inline=True)
    embed.add_field(name="观察周期", value=horizon, inline=True)
    if card.core_thesis:
        embed.add_field(name="核心逻辑", value=card.core_thesis[:1024], inline=False)
    if card.why_now:
        embed.add_field(
            name="为什么现在关注",
            value="\n".join(f"• {item}" for item in card.why_now)[:1024],
            inline=False,
        )
    if card.supporting_points:
        embed.add_field(
            name="观察依据",
            value="\n".join(f"• {item}" for item in card.supporting_points)[:1024],
            inline=False,
        )
    if card.engine_observations:
        embed.add_field(
            name="AXIS 结构观察",
            value="\n".join(f"• {item}" for item in card.engine_observations)[:1024],
            inline=False,
        )
    levels = []
    for level in card.key_levels:
        price = level.get("price")
        note = level.get("note")
        if price is not None or note:
            price_text = price if price is not None else ""
            levels.append(f"{level.get('level_type')}: {price_text} {note or ''}".strip())
    if levels:
        embed.add_field(name="关注位置", value="\n".join(levels)[:1024], inline=False)
    if card.projection_path:
        route_lines = []
        for index, point in enumerate(card.projection_path[:12], start=1):
            price = point.get("price")
            route_lines.append(
                f"P{index} · {point.get('direction', 'FLAT')}"
                + (f" · ${float(price):,.2f}" if isinstance(price, (int, float)) else "")
                + (f" · {point['label']}" if point.get("label") else "")
            )
        embed.add_field(
            name="预测路径（文字）",
            value=" → \n".join(route_lines)[:1024],
            inline=False,
        )
    if card.invalidation:
        embed.add_field(name="失效条件", value=card.invalidation[:1024], inline=False)
    if card.risks:
        embed.add_field(name="风险", value="\n".join(card.risks)[:1024], inline=False)
    if card.market_conditions:
        embed.add_field(
            name="市场前提", value="\n".join(card.market_conditions)[:1024], inline=False
        )
    if card.related_symbols:
        embed.add_field(name="相关观察", value=", ".join(card.related_symbols), inline=False)
    observed = card.observed_at.astimezone(ZoneInfo("America/Toronto"))
    embed.add_field(name="时间", value=observed.strftime("%m/%d · %H:%M ET"), inline=False)
    if image_filename:
        embed.set_image(url=f"attachment://{image_filename}")
    embed.set_footer(text=f"AXIS Analysis · {public_ref}")
    return embed
