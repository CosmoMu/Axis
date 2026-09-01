from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from zoneinfo import ZoneInfo

import discord

from app.domain.analysis_voice import public_analysis_text
from app.domain.public_cards import (
    ActivePublicTrade,
    DailyActiveTrade,
    DailyCategorySummary,
    DailyClosedTrade,
    DailyResultsCard,
    PublicAnalysisCard,
    PublicTradeCard,
    ShortTermEntryCard,
    ShortTermTrackingCard,
)
from app.domain.public_identity import PublicIdentityPolicy
from app.services.analysis_pipeline import AnalysisDraftSnapshot
from app.services.card_review import (
    ReviewDraft,
    missing_field_labels,
    publication_missing_fields,
)
from app.services.official_results import OfficialResult

ACCENT_GREEN = 0x86F7A8
MUTED = 0x9A9F9B
DANGER = 0xD66A6A
PUBLIC_IDENTITY = PublicIdentityPolicy()


def configure_public_identity(policy: PublicIdentityPolicy) -> None:
    """Install the single runtime policy used by every member-facing card builder."""
    global PUBLIC_IDENTITY
    PUBLIC_IDENTITY = policy


def _public(embed: discord.Embed) -> discord.Embed:
    PUBLIC_IDENTITY.assert_public(embed.to_dict(), field="public_card")
    return embed


def _public_trade_sort_key(public_trade_id: str) -> tuple[str, int, str]:
    match = re.fullmatch(r"([A-Z]+)-(\d+)", public_trade_id)
    if match is None:
        return public_trade_id, 2**31 - 1, public_trade_id
    return match.group(1), int(match.group(2)), public_trade_id


def _result_status_emoji(value: Decimal | None) -> str:
    if value is None or value == 0:
        return "➖"
    return "✅" if value > 0 else "❌"


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
    rendered = f"{value:f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"${_number(value)}"


def _percent(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


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
    category = (
        draft.selected_category or draft.category_suggestion
        if isinstance(draft, ReviewDraft)
        else draft.category
    )
    expiry = _expiry_display(draft.expiry, category) if draft.expiry else "—"
    side = {"CALL": "C", "PUT": "P"}.get(draft.option_side or "", "?")
    strike = _number(draft.strike)
    lotto = " (LOTTO)" if draft.is_lotto else ""
    return f"{draft.ticker or '—'} · {expiry} · {strike}{side}{lotto}"


def _short_term_contract(
    card: ShortTermEntryCard | ShortTermTrackingCard,
) -> str:
    expiry = _expiry_display(card.expiry, "SHORT_TERM")
    side = {"CALL": "C", "PUT": "P"}.get(card.option_side, "?")
    lotto = " (LOTTO)" if card.is_lotto else ""
    return f"{card.ticker} · {expiry} · {_number(card.strike)}{side}{lotto}"


def _expiry_display(expiry: date, category: str | None) -> str:
    if category == "LEAPS" or expiry.year != date.today().year:
        return expiry.strftime("%m/%d/%y")
    return expiry.strftime("%m/%d")


def _draft_entry_price(draft: ReviewDraft) -> Decimal | None:
    if draft.action_price is not None:
        return draft.action_price
    if draft.entry_low is not None and draft.entry_high is not None:
        return (draft.entry_low + draft.entry_high) / 2
    return draft.entry_low if draft.entry_low is not None else draft.entry_high


def _review_warning(warning: str) -> str:
    return {
        "ENTRY_PRICE_FILLED_FROM_CURRENT_OPTION_QUOTE": (
            "行情补全：输入未识别到入场价，已填入当前期权参考价，请审核。"
        ),
        "CURRENT_OPTION_QUOTE_UNAVAILABLE": (
            "行情补全失败：当前期权参考价不可用，请手动填写。"
        ),
    }.get(warning, warning)


def _review_warnings(warnings: tuple[str, ...]) -> str:
    return "\n".join(_review_warning(warning) for warning in warnings)[:1024]


def build_review_embed(draft: ReviewDraft) -> discord.Embed:
    if (draft.selected_category or draft.category_suggestion) == "SHORT_TERM":
        return build_short_term_review_embed(draft)
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
    category = CATEGORY_LABELS.get(
        draft.selected_category or draft.category_suggestion or "", "待选择"
    )
    embed = discord.Embed(
        title=f"{title} · {draft.draft_code}",
        description=f"**{action_label(draft)}** · {category}\n{_contract(draft)}",
        color=color,
    )
    price_lines = []
    if draft.entry_low is not None or draft.entry_high is not None:
        price_lines.append(f"入场 {_money(draft.entry_low)}–{_money(draft.entry_high)}")
    if draft.action_price is not None:
        price_lines.append(f"操作 {_money(draft.action_price)}")
    if draft.avg_cost is not None:
        price_lines.append(f"均价 {_money(draft.avg_cost)}")
    price_lines.extend(
        f"{name} {_money(value)}"
        for name, value in (("SL", draft.sl), ("TP1", draft.tp1), ("TP2", draft.tp2))
        if value is not None
    )
    if price_lines:
        embed.add_field(name="价格 / 风控", value=" · ".join(price_lines)[:1024], inline=False)

    position_lines = []
    if draft.position_delta_eighths is not None:
        position_lines.append(f"本次 {_position(draft.position_delta_eighths)}")
    position_lines.append(f"操作后 {_position(draft.position_after_eighths)}")
    if draft.current_pnl_pct is not None:
        position_lines.append(f"当前收益 {_number(draft.current_pnl_pct)}%")
    embed.add_field(name="仓位", value=" · ".join(position_lines), inline=False)

    review_lines = [
        f"Mentor：{draft.mentor_name or '待选择'}",
        f"关联订单：{draft.matched_trade_code or '无'}",
    ]
    missing = publication_missing_fields(draft)
    if missing:
        review_lines.append("发布前必须补齐：" + "、".join(missing_field_labels(missing)))
    embed.add_field(name="审核", value="\n".join(review_lines), inline=False)
    if draft.warnings:
        embed.add_field(name="解析警告", value=_review_warnings(draft.warnings), inline=False)
    if draft.expiry_input:
        embed.add_field(
            name="Internal · Expiry Resolution",
            value=(
                f"输入 {draft.expiry_input} → "
                f"{draft.expiry.strftime('%m/%d/%Y') if draft.expiry else 'unresolved'}"
            ),
            inline=False,
        )
    confidence = _number(draft.parser_confidence)
    embed.set_footer(
        text=f"AXIS Signal · {draft.draft_code} · v{draft.version} · confidence {confidence}"
    )
    return embed


def build_short_term_review_embed(draft: ReviewDraft) -> discord.Embed:
    color = DANGER if draft.status in {"PARSE_FAILED", "DELETED", "PUBLISH_FAILED"} else MUTED
    title = "待审核 · SHORT-TERM"
    if draft.status == "READY":
        title, color = "审核通过 · SHORT-TERM", ACCENT_GREEN
    elif draft.status == "PUBLISHED":
        title, color = "已发布 · SHORT-TERM", ACCENT_GREEN
    elif draft.status == "PUBLISH_FAILED":
        title = "发布失败 · SHORT-TERM"
    elif draft.status == "DELETED":
        title = "已删除 · SHORT-TERM"
    embed = discord.Embed(
        title=title,
        description=_contract(draft),
        color=color,
    )
    embed.add_field(name="入场价格", value=_money(_draft_entry_price(draft)), inline=False)
    if draft.expiry is None:
        expiry_text = "待解析"
    elif draft.expiry_precision == "ZERO_DTE" or (
        draft.expiry_precision == "AUTO_NEAREST" and draft.expiry == date.today()
    ):
        expiry_text = "0DTE"
    elif draft.expiry_precision == "AUTO_NEAREST":
        expiry_text = f"{draft.expiry.strftime('%m/%d')} · 最近到期"
    else:
        expiry_text = draft.expiry.strftime("%m/%d/%Y")
    embed.add_field(name="到期", value=expiry_text, inline=False)
    if draft.expiry_input:
        resolved = draft.expiry.strftime("%m/%d/%Y") if draft.expiry else "unresolved"
        embed.add_field(
            name="Internal · Expiry Source",
            value=f"{draft.expiry_input} → {resolved}",
            inline=False,
        )
    embed.add_field(name="分类", value="SHORT-TERM", inline=False)
    if draft.contract_validation_status == "NOT_FOUND":
        embed.add_field(
            name="Contract not found.",
            value="请选择 Expiry，或编辑 Strike / Side。",
            inline=False,
        )
    if draft.warnings:
        embed.add_field(name="Warnings", value=_review_warnings(draft.warnings), inline=False)
    embed.set_footer(text=f"AXIS Signal · {draft.draft_code} · v{draft.version}")
    return embed


def build_short_term_entry_embed(
    card: ShortTermEntryCard, *, public_ref: str | None = None
) -> discord.Embed:
    embed = discord.Embed(
        title=f"入场 · {card.public_trade_id}",
        description=_short_term_contract(card),
        color=ACCENT_GREEN,
    )
    embed.add_field(name="价格", value=_money(card.entry_price), inline=False)
    embed.add_field(name="\u200b", value="MY RISK IS NOT YOUR RISK.", inline=False)
    if public_ref:
        embed.set_footer(text=f"AXIS · {public_ref}")
    return _public(embed)


def build_short_term_tracking_embed(
    card: ShortTermTrackingCard, *, public_ref: str | None = None
) -> discord.Embed:
    title = {
        "SL": "SL",
        "STOP_TRACKING": "停止追踪",
        "EXPIRED": "到期",
    }.get(card.card_type, card.card_type)
    embed = discord.Embed(
        title=f"{title} · {card.public_trade_id}",
        description=_short_term_contract(card),
        color=(
            DANGER
            if card.card_type == "SL"
            else ACCENT_GREEN if card.return_pct >= 0 else MUTED
        ),
    )
    embed.add_field(name="价格", value=_money(card.price), inline=False)
    if card.card_type == "SL":
        sl_value = "成本价 · 0.00%" if card.return_pct == 0 else f"{card.return_pct:+.2f}%"
        embed.add_field(name="SL", value=sl_value, inline=False)
        embed.add_field(name="状态", value="继续追踪至到期", inline=False)
    else:
        embed.add_field(name="收益", value=f"{card.return_pct:+.2f}%", inline=False)
    if card.card_type in {"STOP_TRACKING", "EXPIRED"} and card.highest_return_pct is not None:
        embed.add_field(name="最高收益", value=f"{card.highest_return_pct:+.2f}%", inline=False)
    if public_ref:
        embed.set_footer(text=f"AXIS Short-Term Event · {public_ref}")
    return _public(embed)


def build_public_preview_embed(card: PublicTradeCard) -> discord.Embed:
    embed = build_public_trade_embed(card)
    embed.title = f"预览 · {action_label(card)}"
    embed.set_footer(text="管理员预览 · 尚未发布")
    return _public(embed)


def build_complete_review_embed(
    draft: ReviewDraft,
    card: PublicTradeCard,
) -> discord.Embed:
    """Show the complete member card while keeping review-only context at the bottom."""

    embed = build_public_trade_embed(card)
    embed.title = f"会员卡片预览 · {embed.title or action_label(card)}"
    review_lines = [
        f"Mentor：{draft.mentor_name or '待选择'}",
        f"关联订单：{draft.matched_trade_code or '无'}",
    ]
    missing = publication_missing_fields(draft)
    if missing:
        review_lines.append("缺失：" + "、".join(missing))
    embed.add_field(name="审核信息", value="\n".join(review_lines)[:1024], inline=False)
    if draft.warnings:
        embed.add_field(name="解析警告", value="\n".join(draft.warnings)[:1024], inline=False)
    embed.set_footer(text=f"AXIS Signal · {draft.draft_code} · v{draft.version}")
    return embed


def build_public_trade_embed(
    card: PublicTradeCard, *, public_ref: str | None = None
) -> discord.Embed:
    if card.category in {"SWING", "LEAPS"} and card.action == "ENTRY":
        return _build_swing_leaps_entry_embed(card, public_ref=public_ref)
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
    embed.set_footer(text=_public_trade_footer(card, public_ref))
    return _public(embed)


def _public_trade_footer(card: PublicTradeCard, public_ref: str | None) -> str:
    if public_ref and re.fullmatch(r"P-\d{4,6}", public_ref):
        return f"AXIS · {public_ref}"
    category = "SWING" if card.category == "SWING" else "LEAPS"
    return f"AXIS · {category}"


def _option_entry_price(card: PublicTradeCard) -> Decimal | None:
    if card.action_price is not None:
        return card.action_price
    if card.entry_low is not None and card.entry_high is not None:
        return (card.entry_low + card.entry_high) / 2
    return card.entry_low if card.entry_low is not None else card.entry_high


def _build_swing_leaps_entry_embed(
    card: PublicTradeCard,
    *,
    public_ref: str | None,
) -> discord.Embed:
    expiry = _expiry_display(card.expiry, card.category) if card.expiry else "—"
    side = {"CALL": "C", "PUT": "P"}.get(card.option_side or "", "?")
    lotto = " (LOTTO)" if card.is_lotto else ""
    contract = "$" + f"{card.ticker or '—'} {expiry} {_number(card.strike)}{side}{lotto}"
    option_entry = _option_entry_price(card)
    if option_entry is not None:
        contract += f" · {_money(option_entry)}"
    embed = discord.Embed(
        title=(
            f"#{card.public_trade_id} · STARTER ENTRY" if card.public_trade_id else "STARTER ENTRY"
        ),
        description=f"**{contract}**",
        color=ACCENT_GREEN,
    )
    if card.current_stock is not None:
        embed.add_field(name="当前股价", value=_money(card.current_stock), inline=False)
    targets = [
        f"{label} {_money(value)}"
        for label, value in (
            ("PT1", card.stock_pt1),
            ("PT2", card.stock_pt2),
            ("PT3", card.stock_pt3),
        )
        if value is not None
    ]
    if targets:
        embed.add_field(name="止盈目标", value="\n".join(targets), inline=False)
    if card.add_zone_low is not None and card.add_zone_high is not None:
        embed.add_field(
            name="Add Zone",
            value=f"{_money(card.add_zone_low)} – {_money(card.add_zone_high)}",
            inline=False,
        )
    if card.stock_sl is not None:
        embed.add_field(name="SL", value=_money(card.stock_sl), inline=True)
    if card.fib_0618 is not None:
        embed.add_field(name="Fib 0.618", value=_money(card.fib_0618), inline=True)
    embed.add_field(
        name="状态",
        value=f"ENTRY TRIGGERED · {_position(card.position_after_eighths)}",
        inline=False,
    )
    if card.public_thesis:
        embed.add_field(name="交易逻辑", value=card.public_thesis[:600], inline=False)
    embed.set_footer(text=_public_trade_footer(card, public_ref))
    return _public(embed)


def build_active_orders_embed(category: str, trades: list[ActivePublicTrade]) -> discord.Embed:
    title = {
        "SWING": "当前波段订单",
        "LEAPS": "当前长期订单",
    }.get(category, "当前订单")
    embed = discord.Embed(title=title, color=ACCENT_GREEN)
    if not trades:
        embed.description = "当前没有进行中的订单。"
        return _public(embed)
    for trade in trades:
        expiry = _expiry_display(trade.expiry, category)
        side = {"CALL": "C", "PUT": "P"}.get(trade.option_side, "?")
        lotto = " (LOTTO)" if trade.is_lotto else ""
        contract = f"{trade.ticker} {expiry} {_number(trade.strike)}{side}{lotto}"
        label = ACTION_LABELS.get(trade.last_public_action, trade.last_public_action)
        embed.add_field(
            name=trade.public_trade_id,
            value=(
                f"{contract}\n{label} · 当前持仓 {_position(trade.position_eighths)}"
                + (f"\n最近持仓成本 {_money(trade.avg_cost)}" if trade.avg_cost is not None else "")
            ),
            inline=False,
        )
    return _public(embed)


def build_official_result_embed(result: OfficialResult) -> discord.Embed:
    side = {"CALL": "C", "PUT": "P"}.get(result.option_side, "?")
    category = "LEAPS" if result.public_trade_id.startswith("LP-") else "SWING"
    expiry = _expiry_display(result.expiry, category)
    contract = f"{result.ticker} · {expiry} · {_number(result.strike)}{side}"
    value = result.final_return_pct.quantize(Decimal("0.01"))
    rendered_return = f"{value:+f}%"
    embed = discord.Embed(
        title=f"已完成 · {result.public_trade_id}",
        description=contract,
        color=ACCENT_GREEN if value >= 0 else DANGER,
    )
    embed.add_field(name="加权最终收益", value=rendered_return, inline=False)
    embed.set_footer(text=f"AXIS Result · {result.public_trade_id}")
    return _public(embed)


def _daily_contract(item: DailyActiveTrade | DailyClosedTrade, category: str) -> str:
    expiry = _expiry_display(item.expiry, category)
    side = {"CALL": "C", "PUT": "P"}.get(item.option_side, "?")
    lotto = " (LOTTO)" if item.is_lotto else ""
    return f"{item.ticker} · {expiry} · {_number(item.strike)}{side}{lotto}"


def build_daily_summary_embeds(summary: DailyCategorySummary) -> list[discord.Embed]:
    category = summary.category.replace("_", "-")
    date_label = summary.session_date.strftime("%Y/%m/%d")
    embed = discord.Embed(title=f"{category} · DAILY SUMMARY", color=ACCENT_GREEN)
    closed_lines: list[str] = []
    for trade in summary.closed[:12]:
        details = _closed_result_text(
            tp_returns=trade.tp_returns,
            highest=trade.highest_return_pct,
            exit_label=trade.exit_label,
            exit_return=trade.exit_return_pct,
            fallback=trade.final_return_pct,
        )
        closed_lines.append(
            f"**{trade.public_trade_id}** · {_daily_contract(trade, summary.category)}\n{details}"
        )
    if len(summary.closed) > 12:
        closed_lines.append(f"另有 {len(summary.closed) - 12} 个今日已完成订单。")
    embed.add_field(
        name="今日关闭",
        value=("\n\n".join(closed_lines) or "今日没有已完成订单。")[:1024],
        inline=False,
    )

    active_lines: list[str] = []
    for trade in summary.active[:12]:
        close_result = (
            "收盘行情暂不可用"
            if trade.unrealized_pnl_pct is None
            else (
                f"收盘 {trade.unrealized_pnl_pct:+.2f}%"
                + (
                    f" · 收盘价 {_money(trade.reference_price)}"
                    if trade.reference_price is not None
                    else ""
                )
            )
        )
        active_lines.append(
            f"**{trade.public_trade_id}** · {_daily_contract(trade, summary.category)}\n"
            f"{close_result} · 当前持仓 {_position(trade.position_eighths)}"
            + (f" · 最近成本 {_money(trade.avg_cost)}" if trade.avg_cost is not None else "")
        )
    if len(summary.active) > 12:
        active_lines.append(f"另有 {len(summary.active) - 12} 个订单，请使用「查看当前持仓订单」。")
    embed.add_field(
        name="当前持仓",
        value=("\n\n".join(active_lines) or "当前没有进行中的订单。")[:1024],
        inline=False,
    )
    embed.set_footer(text=f"AXIS · {date_label} ET · 正式收盘价")
    return [_public(embed)]


def _closed_result_text(
    *,
    tp_returns: tuple[tuple[str, Decimal], ...],
    highest: Decimal | None,
    exit_label: str | None,
    exit_return: Decimal | None,
    fallback: Decimal | None,
) -> str:
    if tp_returns:
        pieces = [f"{label} {value:+.2f}%" for label, value in tp_returns]
        if highest is not None:
            pieces.append(f"最高收益 {highest:+.2f}%")
        return " · ".join(pieces)
    if exit_label is not None:
        pieces = [f"{exit_label} {_percent(exit_return)}"]
        if highest is not None:
            pieces.append(f"最高收益 {highest:+.2f}%")
        return " · ".join(pieces)
    return f"最终收益 {_percent(fallback)}"


def build_daily_results_embed(card: DailyResultsCard) -> discord.Embed:
    embed = discord.Embed(title="AXIS DAILY RESULTS", color=ACCENT_GREEN)
    for label, rows in (
        ("SHORT-TERM", card.short_term),
        ("SWING", card.swing),
        ("LEAPS", card.leaps),
    ):
        lines: list[str] = []
        for row in sorted(rows, key=lambda item: _public_trade_sort_key(item.public_trade_id))[:10]:
            lotto = " (LOTTO)" if row.is_lotto else ""
            contract = (
                f"{row.ticker} {_number(row.strike)}"
                f"{'C' if row.option_side == 'CALL' else 'P'}{lotto}"
            )
            if label == "SHORT-TERM":
                expiry = row.expiry.strftime("%m/%d") if row.expiry is not None else ""
                lines.append(
                    f"{_result_status_emoji(row.displayed_result_pct)} "
                    f"{row.public_trade_id} · {row.ticker} "
                    f"{expiry + ' ' if expiry else ''}{_number(row.strike)}"
                    f"{'C' if row.option_side == 'CALL' else 'P'} "
                    f"{_percent(row.displayed_result_pct)}"
                )
            else:
                lines.append(
                    f"**{row.public_trade_id}** · {contract}\n"
                    + _closed_result_text(
                        tp_returns=row.tp_returns,
                        highest=row.highest_return_pct,
                        exit_label=row.exit_label,
                        exit_return=row.exit_return_pct,
                        fallback=row.mentor_final_return_pct,
                    )
                )
        embed.add_field(
            name=label,
            value=("\n\n".join(lines) or "今日无已完成订单")[:1024],
            inline=False,
        )
    embed.description = (
        f"{card.session_date.isoformat()} ET\nPast performance does not guarantee future results."
    )
    embed.set_footer(text="AXIS Results")
    return _public(embed)


def build_daily_results_snapshot_embed(
    snapshot: dict[str, object],
    *,
    review: bool,
) -> discord.Embed:
    embed = discord.Embed(
        title=str(snapshot.get("title") or "AXIS DAILY RESULTS"),
        color=ACCENT_GREEN,
    )
    description = str(snapshot.get("trading_date") or "")
    if review:
        description += (
            f"\n\n状态：{snapshot.get('status', 'DRAFT')}"
            f"\n自动发布：{snapshot.get('scheduled_publish_at', '16:15 ET')}"
        )
    embed.description = description
    for section in snapshot.get("sections", []):
        if not isinstance(section, dict):
            continue
        lines = section.get("lines")
        value = "今日无已完成订单"
        if isinstance(lines, list) and lines:
            value = "\n\n".join(str(line) for line in lines)
        embed.add_field(
            name=str(section.get("label") or "RESULTS")[:256],
            value=value[:1024],
            inline=False,
        )
    embed.set_footer(text=str(snapshot.get("footer") or "AXIS Results")[:2048])
    return _public(embed)


def _analysis_price(value: object) -> str:
    return f"${float(value):,.2f}" if isinstance(value, (int, float, Decimal)) else ""


def _level_text(level: dict[str, object], *, show_source: bool) -> str:
    price = _analysis_price(level.get("price"))
    high = _analysis_price(level.get("price_high"))
    price_text = f"{price} – {high}" if price and high else price or high
    details = []
    strength = level.get("strength")
    if isinstance(strength, (int, float, Decimal)):
        details.append(f"强度 {float(strength):.0f}")
    description = public_analysis_text(level.get("description") or level.get("note"))
    if description:
        details.append(str(description))
    if show_source:
        details.append("MENTOR" if level.get("source") == "MENTOR_INPUT" else "AXIS")
    return " · ".join(item for item in (price_text, *details) if item)


def _grouped_levels(
    levels: tuple[dict[str, object], ...] | list[dict[str, object]], *, show_source: bool
) -> str:
    labels = (
        (("SUPPORT", "KEY_ZONE"), "关键支撑"),
        (("RESISTANCE", "BREAKOUT", "PIVOT"), "关键压力"),
        (("TARGET",), "目标"),
        (("INVALIDATION",), "失效"),
        (("WATCH", "OTHER"), "关注位置"),
    )
    sections = []
    for roles, label in labels:
        lines = [
            _level_text(item, show_source=show_source)
            for item in levels
            if str(item.get("role") or item.get("level_type")) in roles
        ]
        lines = [line for line in lines if line]
        if lines:
            sections.append(f"**{label}**\n" + "\n".join(lines))
    return "\n\n".join(sections)


def _indicator_text(
    indicators: tuple[dict[str, object], ...] | list[dict[str, object]], *, show_source: bool
) -> str:
    lines = []
    for item in indicators:
        name = item.get("indicator_name")
        if not name:
            continue
        value = item.get("value")
        interpretation = public_analysis_text(item.get("interpretation"))
        source = (
            " · MENTOR"
            if show_source and item.get("source") == "MENTOR_INPUT"
            else " · AXIS"
            if show_source
            else ""
        )
        value_text = f" · {value}" if value is not None else ""
        lines.append(
            f"**{name}**{value_text}{source}" + (f"\n{interpretation}" if interpretation else "")
        )
    return "\n\n".join(lines)


def _scenario_text(
    scenario: dict[str, object] | None,
    path: tuple[dict[str, object], ...] | list[dict[str, object]],
) -> tuple[str, str] | None:
    if not scenario:
        return None
    weight = float(scenario.get("model_weight_percent") or 0)
    if scenario.get("direction_clear") is not True or not path:
        return "主要预测路径", "当前路径不明确，仅保留关键结构位置。"
    lines = []
    for index, point in enumerate(path):
        label = public_analysis_text(point.get("label")) or point.get("type") or "结构位置"
        prefix = "" if index == 0 else "→ "
        lines.append(f"{prefix}{label} {_analysis_price(point.get('price'))}".strip())
    invalidation = _analysis_price(scenario.get("invalidation"))
    if invalidation:
        lines.extend(("", f"**失效**\n{invalidation}"))
    return f"主要预测路径 · {weight:.0f}%", "\n".join(lines)


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
        title=f"FINAL FUSED PREVIEW · {draft.draft_code}",
        description=str(
            public_analysis_text(payload.get("title") or payload.get("summary")) or "需要人工整理"
        ),
        color=DANGER if draft.status == "PARSE_FAILED" else MUTED,
    )
    embed.add_field(
        name="标的",
        value=", ".join(payload.get("symbols", [])) or payload.get("sector") or type_label,
        inline=True,
    )
    embed.add_field(name="当前观点", value=str(payload.get("stance", "WATCH")), inline=True)
    embed.add_field(name="Mentor", value=draft.mentor_name or "尚未选择", inline=True)
    if payload.get("core_thesis"):
        embed.add_field(
            name="核心逻辑",
            value=str(public_analysis_text(payload["core_thesis"]))[:1024],
            inline=False,
        )
    levels = _grouped_levels(payload.get("key_levels", []), show_source=True)
    if levels:
        embed.add_field(name="AXIS 结构观察 · Internal Source", value=levels[:1024], inline=False)
    indicators = _indicator_text(payload.get("indicators", []), show_source=True)
    if indicators:
        embed.add_field(name="指标分析 · Internal Source", value=indicators[:1024], inline=False)
    scenario = _scenario_text(payload.get("top_scenario"), payload.get("prediction_path", []))
    if scenario:
        embed.add_field(name=scenario[0], value=scenario[1][:1024], inline=False)
    if draft.conflicts:
        lines = []
        for conflict in draft.conflicts:
            mentor = ", ".join(
                _analysis_price(value) for value in conflict.get("mentor_values", [])
            )
            axis = ", ".join(
                _analysis_price(value) for value in conflict.get("stock_analyst_values", [])
            )
            lines.append(f"**{conflict.get('field')}**\nMentor {mentor}\nAXIS {axis}")
        embed.add_field(name="Data Conflict", value="\n\n".join(lines)[:1024], inline=False)
    if payload.get("risks"):
        embed.add_field(
            name="主要风险",
            value="\n".join(f"• {public_analysis_text(item)}" for item in payload["risks"])[:1024],
            inline=False,
        )
    if draft.warnings or draft.chart_render_error:
        warnings = [*draft.warnings]
        if draft.chart_render_error:
            warnings.append(f"CHART: {draft.chart_render_error}")
        embed.add_field(name="Warnings", value="\n".join(warnings)[:1024], inline=False)
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
    embed = discord.Embed(
        title=f"{type_label} · {subject}",
        description=public_analysis_text(card.title or card.summary),
        color=ACCENT_GREEN,
    )
    embed.add_field(name="当前观点", value=stance, inline=False)
    if card.core_thesis:
        embed.add_field(
            name="核心逻辑",
            value=str(public_analysis_text(card.core_thesis))[:1024],
            inline=False,
        )
    levels = _grouped_levels(card.key_levels, show_source=False)
    if levels:
        embed.add_field(name="AXIS 结构观察", value=levels[:1024], inline=False)
    profile = card.market_profile
    profile_lines = []
    if profile.get("point_of_control") is not None:
        profile_lines.append(f"**POC**\n{_analysis_price(profile['point_of_control'])}")
    if profile.get("value_area_low") is not None and profile.get("value_area_high") is not None:
        profile_lines.append(
            "**70% Value Area**\n"
            f"{_analysis_price(profile['value_area_low'])} – "
            f"{_analysis_price(profile['value_area_high'])}"
        )
    if profile.get("money_flow_score") is not None:
        profile_lines.append(
            "**资金流向代理**\n"
            f"{profile.get('money_flow_label') or 'NEUTRAL'} · "
            f"{float(profile['money_flow_score']):.0f}/100"
        )
    if profile_lines:
        embed.add_field(
            name="筹码峰与资金分布", value="\n\n".join(profile_lines)[:1024], inline=False
        )
    indicators = _indicator_text(card.indicators, show_source=False)
    if indicators:
        embed.add_field(name="指标分析", value=indicators[:1024], inline=False)
    scenario = _scenario_text(card.top_scenario, card.prediction_path)
    if scenario:
        embed.add_field(name=scenario[0], value=scenario[1][:1024], inline=False)
    risks = [public_analysis_text(item) for item in card.risks if public_analysis_text(item)]
    if card.market_conditions:
        risks.extend(
            public_analysis_text(item)
            for item in card.market_conditions
            if public_analysis_text(item)
        )
    if card.methodology_notice:
        risks.append(public_analysis_text(card.methodology_notice))
    if risks:
        embed.add_field(
            name="主要风险",
            value="\n".join(f"• {item}" for item in dict.fromkeys(risks))[:1024],
            inline=False,
        )
    observed = card.observed_at.astimezone(ZoneInfo("America/Toronto"))
    timestamp = card.market_as_of or observed.strftime("%m/%d · %H:%M ET")
    embed.add_field(name="行情截至", value=str(timestamp)[:100], inline=False)
    if image_filename:
        embed.set_image(url=f"attachment://{image_filename}")
    embed.set_footer(text=f"AXIS Analysis · {public_ref}")
    return _public(embed)
