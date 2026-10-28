from __future__ import annotations

import re
from decimal import Decimal
from fractions import Fraction
from typing import Any

import discord

from app.services.moomoo_activity import MoomooActivityEvent

GREEN = 0x45D7A4
YELLOW = 0xE2C15B
RED = 0xE45868
NEUTRAL = 0x202522
OPTION_CODE = re.compile(r"^(?:US\.)?([A-Z]+)(\d{6})([CP])(\d+)$")
MULTI_STRIKE_CODE = re.compile(r"^(?:US\.)?([A-Z]+)(\d{6})([CP])(\d+(?:/\d+)+)$")
CALENDAR_CODE = re.compile(r"^(?:US\.)?([A-Z]+)(\d{6})([CP])(\d+)/(\d{6})([CP])(\d+)$")


def _number(value: Decimal | str | None, *, money: bool = False) -> str:
    if value is None:
        return "—"
    parsed = Decimal(str(value))
    rendered = f"{parsed:,.4f}".rstrip("0").rstrip(".")
    return f"${rendered}" if money else rendered


def _code(value: str) -> str:
    return value[3:] if value.startswith("US.") else value


def _instrument(value: str) -> tuple[str, bool]:
    code = _code(value)
    match = OPTION_CODE.fullmatch(code)
    if match is None:
        return code, False
    ticker, expiry, side, strike_raw = match.groups()
    strike = Decimal(strike_raw) / Decimal("1000")
    strike_text = (
        f"{strike:.0f}"
        if strike == strike.to_integral_value()
        else f"{strike:f}".rstrip("0").rstrip(".")
    )
    return f"{ticker} {expiry[2:4]}/{expiry[4:6]} {strike_text}{side}", True


def _position_instrument(item: dict[str, Any]) -> tuple[str, str]:
    value = str(item.get("code") or "")
    strategy_type = str(item.get("strategy_type") or "SINGLE").upper()
    code = _code(value)
    calendar = CALENDAR_CODE.fullmatch(code)
    if calendar is not None:
        ticker, near_expiry, near_side, near_strike, far_expiry, far_side, far_strike = (
            calendar.groups()
        )
        if near_side == far_side and near_strike == far_strike:
            return (
                f"{ticker} {near_expiry[2:4]}/{near_expiry[4:6]}–"
                f"{far_expiry[2:4]}/{far_expiry[4:6]} {near_strike}{near_side}",
                "日历价差",
            )
    multi_strike = MULTI_STRIKE_CODE.fullmatch(code)
    if multi_strike is not None:
        ticker, expiry, side, strikes = multi_strike.groups()
        label = {
            "BUTTERFLY": "蝶式",
            "VERTICAL_SPREAD": "垂直价差",
            "SPREAD": "垂直价差",
        }.get(strategy_type, strategy_type)
        return f"{ticker} {expiry[2:4]}/{expiry[4:6]} {strikes}{side}", label
    instrument, _ = _instrument(value)
    labels = {
        "BUTTERFLY": "蝶式",
        "CALENDAR_SPREAD": "日历价差",
        "IRON_BUTTERFLY": "铁蝶式",
        "IRON_CONDOR": "铁鹰式",
        "CONDOR": "鹰式",
        "DIAGONAL_SPREAD": "对角价差",
        "VERTICAL_SPREAD": "垂直价差",
        "SPREAD": "垂直价差",
    }
    return instrument, labels.get(strategy_type, "")


def _position_line(item: dict[str, Any]) -> str:
    instrument, strategy_label = _position_instrument(item)
    is_strategy = bool(strategy_label)
    quantity_unit = "组" if is_strategy else ("张" if _instrument(str(item["code"]))[1] else "股")
    pnl_ratio = item.get("unrealized_pnl_ratio")
    line = (
        f"**{instrument}{f' · {strategy_label}' if strategy_label else ''}** × "
        f"{_number(item.get('quantity'))}{quantity_unit}\n"
        f"成本 {_number(item.get('average_cost'), money=True)}　·　"
        f"现价 {_number(item.get('current_price'), money=True)}　·　"
        f"**{_signed_money(item.get('unrealized_pnl'))}**"
    )
    if pnl_ratio is not None:
        line += f"　**{_signed_percent(pnl_ratio)}**"
    return line


def _signed_percent(value: Decimal | str | None) -> str:
    if value is None:
        return "—"
    parsed = Decimal(str(value))
    sign = "+" if parsed > 0 else ""
    return f"{sign}{parsed.quantize(Decimal('0.01')):f}".rstrip("0").rstrip(".") + "%"


def _signed_money(value: Decimal | str | None) -> str:
    if value is None:
        return "—"
    parsed = Decimal(str(value))
    sign = "+" if parsed > 0 else "-" if parsed < 0 else ""
    return f"{sign}{_number(abs(parsed), money=True)}"


def _position_fraction(value: Decimal | None) -> str | None:
    if value is None or value <= 0:
        return None
    fraction = Fraction(float(value)).limit_denominator(8)
    return f"{fraction.numerator}/{fraction.denominator} 仓位"


def _strategy_identity(event: MoomooActivityEvent) -> tuple[str, str]:
    display = event.strategy_display or _code(event.instrument_code)
    ticker, expiry, contracts = (display.split(" ", 2) + ["", ""])[:3]
    heading = " ".join(item for item in (ticker, expiry) if item)
    return heading or display, contracts


def _strategy_structure(event: MoomooActivityEvent) -> str:
    parts = []
    for leg in event.strategy_legs:
        instrument, _ = _instrument(leg.instrument_code)
        contract = instrument.rsplit(" ", 1)[-1]
        verb = "买" if leg.side.upper().startswith("BUY") else "卖"
        parts.append(f"**{verb} {_number(leg.quantity)}×{contract}**")
    return "　·　".join(parts)


def _strategy_total(event: MoomooActivityEvent) -> Decimal | None:
    if event.price is None:
        return None
    return event.price * event.quantity * Decimal("100")


def _strategy_event_embed(event: MoomooActivityEvent) -> discord.Embed:
    heading, contracts = _strategy_identity(event)
    action_label = {
        "BUY": "买入",
        "ADD": "加仓",
        "SELL": "卖出",
        "CLOSE": "清仓",
    }.get(event.action, event.action)
    positive = (event.return_percent or event.total_return_percent or Decimal("0")) >= 0
    if event.action == "CLOSE":
        description = (
            f"**{contracts}**\n"
            "**策略总收益**\n"
            f"## {_signed_percent(event.total_return_percent)}"
            f"　{_signed_money(event.total_profit_amount)}"
        )
        color = GREEN if positive else RED
    elif event.action == "SELL":
        description = (
            f"**{contracts}**\n"
            f"## {_signed_percent(event.return_percent)}\n"
            f"{_number(event.entry_price, money=True)}  →  "
            f"**{_number(event.price, money=True)}**"
        )
        color = YELLOW if positive else RED
    else:
        price_label = "净成本" if event.strategy_price_kind == "DEBIT" else "净收款"
        description = f"**{contracts}**\n### {price_label} {_number(event.price, money=True)} / 组"
        color = GREEN
    strategy_label = {
        "BUTTERFLY": "蝶式策略",
        "VERTICAL_SPREAD": "垂直价差",
    }.get(event.strategy_type or "", "期权组合")
    embed = discord.Embed(
        title=f"{action_label} · {heading} {strategy_label}",
        description=description,
        color=color,
    )
    embed.add_field(name="策略数量", value=f"**{_number(event.quantity)} 组**")
    total = _strategy_total(event)
    if event.action in {"BUY", "ADD"}:
        total_label = "总投入" if event.strategy_price_kind == "DEBIT" else "总收款"
        embed.add_field(name=total_label, value=f"**{_number(total, money=True)}**")
    elif event.action == "CLOSE":
        embed.add_field(name="平仓价格", value=f"**{_number(event.price, money=True)} / 组**")
    else:
        embed.add_field(name="卖出价格", value=f"**{_number(event.price, money=True)} / 组**")
    structure = _strategy_structure(event)
    if structure:
        embed.add_field(name="组合结构", value=structure, inline=False)
    if event.occurred_at is not None:
        embed.timestamp = event.occurred_at
    embed.set_author(name="AXIS · 1K 账户挑战")
    embed.set_footer(text="Moomoo 只读同步 · 多腿组合已合并")
    return embed


def activity_event_embed(event: MoomooActivityEvent) -> discord.Embed:
    if event.strategy_type in {"BUTTERFLY", "VERTICAL_SPREAD"}:
        return _strategy_event_embed(event)
    instrument, is_option = _instrument(event.instrument_code)
    unit = "张" if is_option else "股"
    positive = (event.return_percent or event.total_return_percent or Decimal("0")) >= 0
    if event.action in {"BUY", "ADD"}:
        is_add = event.action == "ADD"
        embed = discord.Embed(
            title=f"{'加仓' if is_add else '买入'} · {instrument}",
            description=f"### {_number(event.price, money=True)}",
            color=GREEN,
        )
        embed.add_field(
            name="本次加仓" if is_add else "数量",
            value=f"**{_number(event.quantity)} {unit}**",
        )
        if is_add:
            embed.add_field(
                name="当前持仓",
                value=f"**{_number(event.position_quantity)} {unit}**",
            )
            embed.add_field(
                name="最新均价",
                value=f"**{_number(event.position_average_cost, money=True)}**",
            )
    elif event.action == "CLOSE":
        embed = discord.Embed(
            title=f"清仓 · {instrument}",
            description=(
                "**合约总收益**\n"
                f"## {_signed_percent(event.total_return_percent)}"
                f"　{_signed_money(event.total_profit_amount)}"
            ),
            color=GREEN if positive else RED,
        )
        embed.add_field(name="清仓价格", value=f"**{_number(event.price, money=True)}**")
    else:
        fraction = _position_fraction(event.position_fraction)
        embed = discord.Embed(
            title=f"卖出 · {instrument}",
            description=(
                f"## {_signed_percent(event.return_percent)}\n"
                f"{_number(event.entry_price, money=True)}  →  "
                f"**{_number(event.price, money=True)}**"
            ),
            color=YELLOW if positive else RED,
        )
        embed.add_field(name="本次卖出", value=f"**{_number(event.quantity)} {unit}**")
        if fraction:
            embed.add_field(name="仓位", value=f"**{fraction}**")
    if event.occurred_at is not None:
        embed.timestamp = event.occurred_at
    embed.set_author(name="AXIS · 1K 账户挑战")
    embed.set_footer(text="Moomoo 只读同步")
    return embed


def activity_event_text(event: MoomooActivityEvent) -> str:
    if event.strategy_type in {"BUTTERFLY", "VERTICAL_SPREAD"}:
        heading, contracts = _strategy_identity(event)
        action_label = {
            "BUY": "买入",
            "ADD": "加仓",
            "SELL": "卖出",
            "CLOSE": "清仓",
        }.get(event.action, event.action)
        price_label = "净成本" if event.strategy_price_kind == "DEBIT" else "净收款"
        strategy_label = (
            "蝶式策略" if event.strategy_type == "BUTTERFLY" else "垂直价差"
        )
        return (
            f"**{action_label} · {heading} {strategy_label}**\n"
            f"{contracts}\n"
            f"{price_label} **{_number(event.price, money=True)} / 组**"
            f" · {_number(event.quantity)}组\n"
            f"{_strategy_structure(event)}"
        )
    instrument, is_option = _instrument(event.instrument_code)
    unit = "张" if is_option else "股"
    if event.action in {"BUY", "ADD"}:
        if event.action == "ADD":
            return (
                f"**加仓** · {instrument} @ {_number(event.price, money=True)}\n"
                f"本次 {_number(event.quantity)}{unit} · "
                f"当前 {_number(event.position_quantity)}{unit}\n"
                f"最新均价 **{_number(event.position_average_cost, money=True)}**"
            )
        return (
            f"**买入** · {instrument} @ {_number(event.price, money=True)}\n"
            f"{_number(event.quantity)}{unit}"
        )
    if event.action == "CLOSE":
        return (
            f"**清仓** · {instrument} @ {_number(event.price, money=True)}\n"
            f"合约总收益 **{_signed_percent(event.total_return_percent)}**"
            f" · **{_signed_money(event.total_profit_amount)}**"
        )
    fraction = _position_fraction(event.position_fraction)
    detail = f"{_number(event.quantity)}{unit}"
    if fraction:
        detail += f" · {fraction}"
    return (
        f"**卖出** · {instrument} @ {_number(event.price, money=True)}\n"
        f"**{_signed_percent(event.return_percent)}**"
        f" · {_number(event.entry_price, money=True)} → {_number(event.price, money=True)}\n"
        f"{detail}"
    )


def daily_summary_embeds(snapshot: dict[str, Any]) -> list[discord.Embed]:
    session_date = str(snapshot.get("session_date") or "")
    accounts = list(snapshot.get("accounts") or [])
    positions = list(snapshot.get("positions") or [])
    performance = dict(snapshot.get("performance") or {})
    win_rate = (
        _signed_percent(performance.get("win_rate")).lstrip("+")
        if performance.get("win_rate") is not None
        else "—"
    )
    average_win = (
        _signed_percent(performance.get("average_win"))
        if performance.get("average_win") is not None
        else "—"
    )
    average_loss = (
        _signed_percent(performance.get("average_loss"))
        if performance.get("average_loss") is not None
        else "—"
    )
    change = next(
        (
            Decimal(str(item["post_fee_return_percent"]))
            for item in accounts
            if item.get("post_fee_return_percent") is not None
        ),
        None,
    )
    closed_count = int(performance.get("closed_count", 0))
    win_count = int(performance.get("win_count", 0))
    loss_count = max(0, closed_count - win_count)
    color = GREEN if change is None or change >= 0 else RED
    first = discord.Embed(
        title=f"1K 挑战 · 收盘总结 · {session_date}",
        color=color,
        description=(f"今日完整交易 **{closed_count}** 笔　·　**{win_count} 胜 {loss_count} 负**"),
    )
    first.set_author(name="AXIS · 1K 账户挑战")
    if accounts:
        lines = []
        for item in accounts:
            line = f"**日初净值**　{_number(item.get('opening_equity'), money=True)}"
            pre_fee_equity = item.get("pre_fee_equity") or item.get("equity")
            post_fee_equity = item.get("post_fee_equity") or item.get("equity")
            commission = item.get("commission")
            commission_text = _number(commission, money=True)
            if commission is not None and Decimal(str(commission)) > 0:
                commission_text = f"-{commission_text}"
            line += f"\n**收盘净值 · 扣费前**　{_number(pre_fee_equity, money=True)}"
            line += f"\n**佣金及交易费**　{commission_text}"
            line += f"\n**收盘净值 · 扣费后**　{_number(post_fee_equity, money=True)}"
            if item.get("post_fee_return_percent") is not None:
                line += (
                    f"\n**今日净收益**　{_signed_money(item.get('post_fee_profit'))}"
                    f"　**{_signed_percent(item['post_fee_return_percent'])}**"
                )
            lines.append(line)
        first.add_field(name="账户状态", value="\n".join(lines)[:1024], inline=False)
    first.add_field(
        name="胜率",
        value=f"**{win_rate}**" if win_rate != "—" else "—",
        inline=True,
    )
    first.add_field(
        name="平均盈利",
        value=f"**{average_win}**" if average_win != "—" else "—",
        inline=True,
    )
    first.add_field(
        name="平均亏损",
        value=f"**{average_loss}**" if average_loss != "—" else "—",
        inline=True,
    )
    position_lines = []
    for item in positions:
        position_lines.append(_position_line(item))
    if position_lines:
        first.add_field(name="当前持仓", value="\n\n".join(position_lines[:5])[:1024], inline=False)
    else:
        first.add_field(name="当前持仓", value="无持仓", inline=False)
    first.set_footer(
        text=(
            "统计仅含当天完整清仓交易且不含费用 · "
            "费用按 Moomoo Canada 公开费率计算 · 扣费后余额作为下一交易日基准"
        )
    )
    embeds = [first]
    for offset in range(5, len(position_lines), 5):
        embed = discord.Embed(
            title=f"当前持仓 · PAGE {offset // 5 + 1}",
            color=NEUTRAL,
        )
        embed.description = "\n\n".join(position_lines[offset : offset + 5])
        embed.set_author(name="AXIS · 1K 账户挑战")
        embed.set_footer(text="Moomoo 只读同步")
        embeds.append(embed)
    return embeds


def daily_summary_messages(snapshot: dict[str, Any]) -> list[str]:
    session_date = str(snapshot.get("session_date") or "")
    accounts = list(snapshot.get("accounts") or [])
    positions = list(snapshot.get("positions") or [])
    performance = dict(snapshot.get("performance") or {})
    win_rate = (
        _signed_percent(performance.get("win_rate")).lstrip("+")
        if performance.get("win_rate") is not None
        else "—"
    )
    average_win = (
        _signed_percent(performance.get("average_win"))
        if performance.get("average_win") is not None
        else "—"
    )
    average_loss = (
        _signed_percent(performance.get("average_loss"))
        if performance.get("average_loss") is not None
        else "—"
    )
    sections = [f"**1K 挑战 · 收盘汇总 · {session_date}**\n当前持仓 {len(positions)} 项"]
    if accounts:
        sections.append(
            "**账户状态**\n"
            + "\n".join(
                f"日初 {_number(item.get('opening_equity'), money=True)}\n"
                f"佣金及费用 {_number(item.get('commission'), money=True)}\n"
                f"扣费前 {_number(item.get('pre_fee_equity') or item.get('equity'), money=True)}"
                + (
                    f" · {_signed_percent(item.get('pre_fee_return_percent'))}"
                    f" · {_signed_money(item.get('pre_fee_profit'))}"
                    if item.get("pre_fee_return_percent") is not None
                    else ""
                )
                + (
                    "\n扣费后 "
                    f"{_number(item.get('post_fee_equity') or item.get('equity'), money=True)}"
                )
                + (
                    f" · {_signed_percent(item.get('post_fee_return_percent'))}"
                    f" · {_signed_money(item.get('post_fee_profit'))}"
                    if item.get("post_fee_return_percent") is not None
                    else ""
                )
                for item in accounts
            )
        )
    sections.append(
        "**今日表现 · 仅完整清仓交易**\n"
        f"胜率 {win_rate}"
        f" · 平均盈利 {average_win}"
        f" · 平均亏损 {average_loss}"
    )
    if positions:
        sections.append("**当前持仓**\n" + "\n".join(_position_line(item) for item in positions))
    else:
        sections.append("**当前持仓**\n无持仓")
    pages: list[str] = []
    current = ""
    for section in sections:
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) <= 1900:
            current = candidate
            continue
        if current:
            pages.append(current)
        while len(section) > 1900:
            cut = section.rfind("\n", 0, 1900)
            cut = cut if cut > 0 else 1900
            pages.append(section[:cut])
            section = section[cut:].lstrip()
        current = section
    if current:
        pages.append(current)
    return [
        f"{page}\n\n*AXIS · 费用按 Moomoo Canada 公开费率计算 · 扣费后余额为下个交易日基准*"
        for page in pages
    ]
