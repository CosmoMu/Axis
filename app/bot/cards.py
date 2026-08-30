from __future__ import annotations

from decimal import Decimal

import discord

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


def action_label(draft: ReviewDraft) -> str:
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


def _contract(draft: ReviewDraft) -> str:
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


def build_public_preview_embed(draft: ReviewDraft) -> discord.Embed:
    embed = discord.Embed(
        title=f"预览 · {action_label(draft)}",
        description=_contract(draft),
        color=ACCENT_GREEN,
    )
    if draft.entry_low is not None or draft.entry_high is not None:
        embed.add_field(
            name="入场区间",
            value=f"{_money(draft.entry_low)} – {_money(draft.entry_high)}",
            inline=False,
        )
    if draft.action_price is not None:
        embed.add_field(name="本次操作价格", value=_money(draft.action_price), inline=False)
    if draft.position_delta_eighths is not None:
        embed.add_field(
            name="本次操作仓位", value=_position(draft.position_delta_eighths), inline=True
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
    embed.set_footer(text="管理员预览 · 尚未发布")
    return embed
