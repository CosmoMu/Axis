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


def activity_event_embed(event: MoomooActivityEvent) -> discord.Embed:
    instrument, is_option = _instrument(event.instrument_code)
    unit = "张" if is_option else "股"
    positive = (event.return_percent or event.total_return_percent or Decimal("0")) >= 0
    if event.action == "BUY":
        embed = discord.Embed(
            title=f"买入 · {instrument}",
            description=f"### {_number(event.price, money=True)}",
            color=GREEN,
        )
        embed.add_field(name="数量", value=f"**{_number(event.quantity)} {unit}**")
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
    instrument, is_option = _instrument(event.instrument_code)
    unit = "张" if is_option else "股"
    if event.action == "BUY":
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
    change = next(
        (
            Decimal(str(item["equity_change_percent"]))
            for item in accounts
            if item.get("equity_change_percent") is not None
        ),
        None,
    )
    color = GREEN if change is None or change >= 0 else RED
    first = discord.Embed(
        title=f"收盘汇总 · {session_date}",
        color=color,
        description=f"当前持仓 **{len(positions)}** 项",
    )
    first.set_author(name="AXIS · 1K 账户挑战")
    if accounts:
        lines = []
        for item in accounts:
            line = f"### {_number(item.get('equity'), money=True)}"
            if item.get("equity_change_percent") is not None:
                line += f"\n相比昨日 **{_signed_percent(item['equity_change_percent'])}**"
            lines.append(line)
        first.add_field(name="账户状态", value="\n".join(lines)[:1024], inline=False)
    position_lines = [
        (
            f"**{_instrument(str(item['code']))[0]}** × {_number(item.get('quantity'))}"
            f"{'张' if _instrument(str(item['code']))[1] else '股'}\n"
            f"成本 {_number(item.get('average_cost'), money=True)}　·　"
            f"现价 {_number(item.get('current_price'), money=True)}　·　"
            f"**{_signed_money(item.get('unrealized_pnl'))}**"
        )
        for item in positions
    ]
    if position_lines:
        first.add_field(name="当前持仓", value="\n\n".join(position_lines[:5])[:1024], inline=False)
    else:
        first.add_field(name="当前持仓", value="无持仓", inline=False)
    first.set_footer(text="美东收盘后自动汇总 · Moomoo 只读同步")
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
    sections = [
        f"**1K 挑战 · 收盘汇总 · {session_date}**\n"
        f"当前持仓 {len(positions)} 项"
    ]
    if accounts:
        sections.append(
            "**账户状态**\n"
            + "\n".join(
                f"总资产 {_number(item.get('equity'), money=True)}"
                + (
                    f" · 相比昨日 {_signed_percent(item.get('equity_change_percent'))}"
                    if item.get("equity_change_percent") is not None
                    else ""
                )
                for item in accounts
            )
        )
    if positions:
        sections.append(
            "**当前持仓**\n"
            + "\n".join(
                f"{_instrument(str(item['code']))[0]} × {_number(item.get('quantity'))}"
                f"{'张' if _instrument(str(item['code']))[1] else '股'}\n"
                f"成本 {_number(item.get('average_cost'), money=True)}\n"
                f"现价 {_number(item.get('current_price'), money=True)}\n"
                f"浮动盈亏 {_signed_money(item.get('unrealized_pnl'))}"
                for item in positions
            )
        )
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
    return [f"{page}\n\n*AXIS · 美东收盘后自动汇总 · 只读*" for page in pages]
