from __future__ import annotations

from decimal import Decimal
from typing import Any

import discord

from app.services.moomoo_activity import MoomooActivityEvent

GREEN = 0x45D7A4
YELLOW = 0xE2C15B
RED = 0xE45868
NEUTRAL = 0x202522


def _number(value: Decimal | str | None, *, money: bool = False) -> str:
    if value is None:
        return "—"
    parsed = Decimal(str(value))
    rendered = f"{parsed:,.4f}".rstrip("0").rstrip(".")
    return f"${rendered}" if money else rendered


def _code(value: str) -> str:
    return value[3:] if value.startswith("US.") else value


def activity_event_embed(event: MoomooActivityEvent) -> discord.Embed:
    is_buy = event.side.upper().startswith("BUY")
    if event.kind == "FILL":
        title = "1K 挑战 · 买入成交" if is_buy else "1K 挑战 · 卖出成交"
        color = GREEN if is_buy else YELLOW
        state = "已成交"
    else:
        state_map = {
            "SUBMITTED": "委托已提交",
            "CANCELLED": "委托已取消",
            "REJECTED": "委托被拒绝",
        }
        state = state_map.get(event.status or "", event.status or "订单更新")
        title = f"1K 挑战 · {state}"
        color = RED if event.status == "REJECTED" else NEUTRAL
    embed = discord.Embed(title=title, color=color)
    embed.add_field(name="标的", value=_code(event.instrument_code), inline=True)
    embed.add_field(name="方向", value="买入" if is_buy else "卖出", inline=True)
    embed.add_field(name="数量", value=_number(event.quantity), inline=True)
    embed.add_field(
        name="成交价" if event.kind == "FILL" else "委托价",
        value=_number(event.price, money=True),
        inline=True,
    )
    embed.add_field(name="状态", value=state, inline=True)
    embed.add_field(name="账户", value=event.account_label, inline=True)
    if event.occurred_at is not None:
        embed.timestamp = event.occurred_at
    embed.set_footer(text="AXIS · Moomoo 只读同步")
    return embed


def activity_event_text(event: MoomooActivityEvent) -> str:
    is_buy = event.side.upper().startswith("BUY")
    direction = "买入" if is_buy else "卖出"
    if event.kind == "FILL":
        state = "成交"
        price_label = "成交价"
    else:
        state = {
            "SUBMITTED": "委托已提交",
            "CANCELLED": "委托已取消",
            "REJECTED": "委托被拒绝",
        }.get(event.status or "", event.status or "订单更新")
        price_label = "委托价"
    return (
        f"**1K 挑战 · {state}**\n"
        f"{direction} **{_code(event.instrument_code)}** × {_number(event.quantity)}"
        f" · {price_label} {_number(event.price, money=True)}\n"
        f"{event.account_label} · Moomoo 只读同步"
    )


def daily_summary_embeds(snapshot: dict[str, Any]) -> list[discord.Embed]:
    session_date = str(snapshot.get("session_date") or "")
    fills = list(snapshot.get("fills") or [])
    accounts = list(snapshot.get("accounts") or [])
    positions = list(snapshot.get("positions") or [])
    first = discord.Embed(
        title=f"1K 挑战 · 收盘汇总 · {session_date}",
        color=GREEN,
        description=f"今日成交 {len(fills)} 笔 · 当前持仓 {len(positions)} 项",
    )
    if accounts:
        lines = []
        for item in accounts:
            lines.append(
                f"**{item['account']}** · 总资产 {_number(item.get('equity'), money=True)}"
                f" · 现金 {_number(item.get('cash'), money=True)}"
                f" · 购买力 {_number(item.get('buying_power'), money=True)}"
            )
        first.add_field(name="账户概览", value="\n".join(lines)[:1024], inline=False)
    grouped_fills: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in fills:
        key = (str(item["account"]), str(item["code"]), str(item["side"]))
        group = grouped_fills.setdefault(
            key,
            {
                "account": item["account"],
                "code": item["code"],
                "side": item["side"],
                "quantity": Decimal("0"),
                "notional": Decimal("0"),
                "count": 0,
            },
        )
        quantity = Decimal(str(item["quantity"]))
        price = Decimal(str(item["price"]))
        group["quantity"] += quantity
        group["notional"] += quantity * price
        group["count"] += 1
    fill_groups = list(grouped_fills.values())
    if fill_groups:
        lines = [
            f"{'买入' if str(item['side']).startswith('BUY') else '卖出'} "
            f"**{_code(str(item['code']))}** × {_number(item['quantity'])}"
            f" · 均价 {_number(item['notional'] / item['quantity'], money=True)}"
            f" · {item['count']} 笔 · {item['account']}"
            for item in fill_groups[:10]
        ]
        first.add_field(name="今日成交汇总", value="\n".join(lines)[:1024], inline=False)
    else:
        first.add_field(name="今日成交", value="无", inline=False)
    first.set_footer(text="AXIS · 美东收盘后自动汇总 · 只读")
    embeds = [first]
    for offset in range(10, len(fill_groups), 10):
        chunk = fill_groups[offset : offset + 10]
        embed = discord.Embed(
            title=f"今日成交汇总 · 第 {offset // 10 + 1} 页",
            color=NEUTRAL,
        )
        for item in chunk:
            average = item["notional"] / item["quantity"]
            embed.add_field(
                name=(
                    f"{'买入' if str(item['side']).startswith('BUY') else '卖出'}"
                    f" · {_code(str(item['code']))}"
                ),
                value=(
                    f"数量 {_number(item['quantity'])} · 均价 {_number(average, money=True)}"
                    f" · {item['count']} 笔\n{item['account']}"
                ),
                inline=False,
            )
        embeds.append(embed)
    for offset in range(0, len(positions), 10):
        chunk = positions[offset : offset + 10]
        embed = discord.Embed(
            title=f"当前持仓 · 第 {offset // 10 + 1} 页",
            color=NEUTRAL,
        )
        for item in chunk:
            value = (
                f"数量 {_number(item.get('quantity'))}"
                f" · 成本 {_number(item.get('average_cost'), money=True)}\n"
                f"现价 {_number(item.get('current_price'), money=True)}"
                f" · 浮动盈亏 {_number(item.get('unrealized_pnl'), money=True)}\n"
                f"{item.get('account', '')}"
            )
            embed.add_field(name=_code(str(item.get("code") or "—")), value=value, inline=False)
        embed.set_footer(text="AXIS · Moomoo 只读同步")
        embeds.append(embed)
    return embeds


def daily_summary_messages(snapshot: dict[str, Any]) -> list[str]:
    session_date = str(snapshot.get("session_date") or "")
    fills = list(snapshot.get("fills") or [])
    accounts = list(snapshot.get("accounts") or [])
    positions = list(snapshot.get("positions") or [])
    sections = [
        f"**1K 挑战 · 收盘汇总 · {session_date}**\n"
        f"今日成交 {len(fills)} 笔 · 当前持仓 {len(positions)} 项"
    ]
    if accounts:
        sections.append(
            "**账户状态**\n"
            + "\n".join(
                f"{item['account']} · 总资产 {_number(item.get('equity'), money=True)}"
                f" · 现金 {_number(item.get('cash'), money=True)}"
                f" · 购买力 {_number(item.get('buying_power'), money=True)}"
                for item in accounts
            )
        )
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in fills:
        key = (str(item["account"]), str(item["code"]), str(item["side"]))
        group = grouped.setdefault(
            key,
            {**item, "quantity": Decimal("0"), "notional": Decimal("0"), "count": 0},
        )
        quantity = Decimal(str(item["quantity"]))
        group["quantity"] += quantity
        group["notional"] += quantity * Decimal(str(item["price"]))
        group["count"] += 1
    if grouped:
        sections.append(
            "**今日成交汇总**\n"
            + "\n".join(
                f"{'买入' if str(item['side']).startswith('BUY') else '卖出'} "
                f"{_code(str(item['code']))} × {_number(item['quantity'])}"
                f" · 均价 {_number(item['notional'] / item['quantity'], money=True)}"
                f" · {item['count']} 笔"
                for item in grouped.values()
            )
        )
    if positions:
        sections.append(
            "**当前持仓**\n"
            + "\n".join(
                f"{_code(str(item['code']))} × {_number(item.get('quantity'))}"
                f" · 成本 {_number(item.get('average_cost'), money=True)}"
                f" · 现价 {_number(item.get('current_price'), money=True)}"
                f" · 浮动盈亏 {_number(item.get('unrealized_pnl'), money=True)}"
                for item in positions
            )
        )
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
