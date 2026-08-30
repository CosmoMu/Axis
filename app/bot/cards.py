from __future__ import annotations

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
    ShortTermActiveTrade,
    ShortTermDailySummary,
    ShortTermEntryCard,
    ShortTermTrackingCard,
)
from app.domain.public_identity import PublicIdentityPolicy
from app.services.analysis_pipeline import AnalysisDraftSnapshot
from app.services.card_review import ReviewDraft, publication_missing_fields
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
    expiry = draft.expiry.strftime("%m/%d/%Y") if draft.expiry else "—"
    side = {"CALL": "C", "PUT": "P"}.get(draft.option_side or "", "?")
    strike = _number(draft.strike)
    return f"{draft.ticker or '—'} · {expiry} · {strike}{side}"


def _short_term_contract(
    card: ShortTermEntryCard | ShortTermTrackingCard | ShortTermActiveTrade,
) -> str:
    expiry = card.expiry.strftime("%m/%d/%Y")
    side = {"CALL": "C", "PUT": "P"}.get(card.option_side, "?")
    return f"{card.ticker} · {expiry} · {_number(card.strike)}{side}"


def _draft_entry_price(draft: ReviewDraft) -> Decimal | None:
    if draft.action_price is not None:
        return draft.action_price
    if draft.entry_low is not None and draft.entry_high is not None:
        return (draft.entry_low + draft.entry_high) / 2
    return draft.entry_low if draft.entry_low is not None else draft.entry_high


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
        review_lines.append("缺失：" + "、".join(missing))
    embed.add_field(name="审核", value="\n".join(review_lines), inline=False)
    if draft.warnings:
        embed.add_field(name="解析警告", value="\n".join(draft.warnings)[:1024], inline=False)
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
    embed.add_field(name="分类", value="SHORT-TERM", inline=False)
    if draft.warnings:
        embed.add_field(name="Warnings", value="\n".join(draft.warnings)[:1024], inline=False)
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
        "TP": "TP",
        "RUNNER": "RUNNER",
        "STOP_TRACKING": "停止追踪",
    }.get(card.card_type, "TP")
    embed = discord.Embed(
        title=f"{title} · {card.public_trade_id}",
        description=_short_term_contract(card),
        color=ACCENT_GREEN if card.return_pct >= 0 else MUTED,
    )
    embed.add_field(name="价格", value=_money(card.price), inline=False)
    embed.add_field(name="收益", value=f"{card.return_pct:+.2f}%", inline=False)
    if card.card_type == "STOP_TRACKING" and card.highest_return_pct is not None:
        embed.add_field(name="最高收益", value=f"{card.highest_return_pct:+.2f}%", inline=False)
    if public_ref:
        embed.set_footer(text=f"AXIS Short-Term Event · {public_ref}")
    return _public(embed)


def build_public_preview_embed(card: PublicTradeCard) -> discord.Embed:
    embed = build_public_trade_embed(card)
    embed.title = f"预览 · {action_label(card)}"
    embed.set_footer(text="管理员预览 · 尚未发布")
    return _public(embed)


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
    return _public(embed)


def build_active_orders_embed(
    category: str, trades: list[ActivePublicTrade] | list[ShortTermActiveTrade]
) -> discord.Embed:
    title = {
        "SHORT_TERM": "当前短线订单",
        "SWING": "当前波段订单",
        "LEAPS": "当前长期订单",
    }.get(category, "当前订单")
    embed = discord.Embed(title=title, color=ACCENT_GREEN)
    if not trades:
        embed.description = "当前没有进行中的订单。"
        return _public(embed)
    if category == "SHORT_TERM":
        for item in trades:
            if not isinstance(item, ShortTermActiveTrade):
                continue
            quote = (
                "行情暂不可用"
                if item.current_price is None or item.current_return_pct is None
                else f"{_money(item.current_price)} · {item.current_return_pct:+.2f}%"
            )
            embed.add_field(
                name=item.public_trade_id,
                value=f"{_short_term_contract(item)}\n{quote}",
                inline=False,
            )
        return _public(embed)
    for trade in trades:
        if not isinstance(trade, ActivePublicTrade):
            continue
        expiry = trade.expiry.strftime("%m/%d")
        side = {"CALL": "C", "PUT": "P"}.get(trade.option_side, "?")
        contract = f"{trade.ticker} {expiry} {_number(trade.strike)}{side}"
        label = ACTION_LABELS.get(trade.last_public_action, trade.last_public_action)
        embed.add_field(
            name=trade.public_trade_id,
            value=f"{contract}\n{label} · 当前持仓 {_position(trade.position_eighths)}",
            inline=False,
        )
    return _public(embed)


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
    return _public(embed)


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
    return [_public(active), _public(closed)]


def build_short_term_daily_summary_embed(summary: ShortTermDailySummary) -> discord.Embed:
    embed = discord.Embed(title="SHORT-TERM · DAILY SUMMARY", color=ACCENT_GREEN)
    if summary.ended:
        lines = [
            (
                f"**{row.public_trade_id}** · {row.ticker} {_number(row.strike)}"
                f"{'C' if row.option_side == 'CALL' else 'P'}\n"
                f"结束 {row.tracking_end_return_pct:+.2f}% · "
                f"最高 {row.highest_return_pct:+.2f}% · 最低 {row.lowest_return_pct:+.2f}%"
            )
            for row in summary.ended[:12]
            if row.tracking_end_return_pct is not None
        ]
        embed.add_field(
            name="今日停止追踪",
            value=("\n\n".join(lines) or "—")[:1024],
            inline=False,
        )
    else:
        embed.add_field(name="今日停止追踪", value="无", inline=False)
    if summary.active:
        lines = [
            (
                f"**{row.public_trade_id}** · {row.ticker} {_number(row.strike)}"
                f"{'C' if row.option_side == 'CALL' else 'P'}\n"
                f"当前 {row.current_return_pct:+.2f}% · "
                f"最高 {row.highest_return_pct:+.2f}% · 最低 {row.lowest_return_pct:+.2f}%"
            )
            for row in summary.active[:12]
            if row.current_return_pct is not None
        ]
        embed.add_field(
            name="继续追踪",
            value=("\n\n".join(lines) or "—")[:1024],
            inline=False,
        )
    else:
        embed.add_field(name="继续追踪", value="无", inline=False)
    embed.set_footer(text=f"AXIS · {summary.session_date:%Y/%m/%d} ET")
    return _public(embed)


def build_daily_results_embed(card: DailyResultsCard) -> discord.Embed:
    embed = discord.Embed(title="AXIS DAILY RESULTS", color=ACCENT_GREEN)
    for label, rows in (
        ("SHORT-TERM", card.short_term),
        ("SWING", card.swing),
        ("LEAPS", card.leaps),
    ):
        lines: list[str] = []
        for row in rows[:10]:
            contract = (
                f"{row.ticker} {_number(row.strike)}{'C' if row.option_side == 'CALL' else 'P'}"
            )
            if label == "SHORT-TERM":
                lines.append(
                    f"**{row.public_trade_id}** · {contract}\n"
                    f"Tracking End {_percent(row.tracking_end_return_pct)} · "
                    f"Maximum Return {_percent(row.maximum_return_pct)} · "
                    f"Maximum Drawdown {_percent(row.maximum_drawdown_pct)}"
                )
            elif row.mentor_final_return_pct is not None:
                lines.append(
                    f"**{row.public_trade_id}** · {contract}\n"
                    f"加权最终收益 {row.mentor_final_return_pct:+.2f}%"
                )
        embed.add_field(
            name=label,
            value=("\n\n".join(lines) or "今日无已完成订单")[:1024],
            inline=False,
        )
    embed.set_footer(text=f"AXIS Results · {card.session_date:%Y/%m/%d} ET")
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
            f"**{name}**{value_text}{source}"
            + (f"\n{interpretation}" if interpretation else "")
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
            public_analysis_text(payload.get("title") or payload.get("summary"))
            or "需要人工整理"
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
