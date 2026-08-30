from __future__ import annotations

from decimal import Decimal

import discord

from app.domain.public_cards import ActivePublicTrade, PublicTradeCard
from app.services.card_review import ReviewDraft, publication_missing_fields

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
    embed.add_field(
        name="操作后持仓", value=_position(draft.position_after_eighths), inline=True
    )
    if draft.avg_cost is not None:
        embed.add_field(name="操作后平均成本", value=_money(draft.avg_cost), inline=True)
    if draft.current_pnl_pct is not None:
        embed.add_field(
            name="当前收益", value=f"{_number(draft.current_pnl_pct)}%", inline=True
        )
    for name, value in (("SL", draft.sl), ("TP1", draft.tp1), ("TP2", draft.tp2)):
        if value is not None:
            embed.add_field(name=name, value=_money(value), inline=True)
    embed.add_field(
        name="分类",
        value=(
            CATEGORY_LABELS.get(draft.selected_category or "", "尚未选择")
            + (
                "\n建议："
                + CATEGORY_LABELS.get(
                    draft.category_suggestion, draft.category_suggestion
                )
                if draft.category_suggestion and not draft.selected_category
                else ""
            )
        ),
        inline=True,
    )
    embed.add_field(name="Mentor", value=draft.mentor_name or "尚未选择", inline=True)
    embed.add_field(
        name="对应订单", value=draft.matched_trade_code or "尚未关联", inline=True
    )
    missing = publication_missing_fields(draft)
    if missing:
        embed.add_field(name="发布前缺失", value="、".join(missing), inline=False)
    if draft.warnings:
        embed.add_field(name="解析警告", value="\n".join(draft.warnings)[:1024], inline=False)
    confidence = _number(draft.parser_confidence)
    embed.set_footer(
        text=f"AXIS Draft ID: {draft.id} · v{draft.version} · confidence {confidence}"
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
    embed.add_field(
        name=after_label, value=_position(card.position_after_eighths), inline=True
    )
    if card.pnl_pct is not None:
        pnl_label = "本次收益" if card.action in {"TP1", "TP2", "CLOSE"} else "当前收益"
        embed.add_field(
            name=pnl_label, value=f"{_number(card.pnl_pct)}%", inline=True
        )
    sl_label = "新 SL" if card.action in {"TP1", "TP2", "ADD", "UPDATE"} else "SL"
    for name, value in ((sl_label, card.sl), ("TP1", card.tp1), ("TP2", card.tp2)):
        if value is not None:
            embed.add_field(name=name, value=_money(value), inline=True)
    if public_ref:
        embed.set_footer(text=f"AXIS · {public_ref}")
    return embed


def build_active_orders_embed(
    category: str, trades: list[ActivePublicTrade]
) -> discord.Embed:
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
