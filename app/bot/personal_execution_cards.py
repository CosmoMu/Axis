from __future__ import annotations

from decimal import Decimal

import discord

from app.services.personal_execution import (
    OrderView,
    PersonalExecutionStatus,
    PositionView,
)

AXIS_GREEN = 0x86F7A8
QUIET_BLACK = 0x111411


def _money(value: Decimal | None) -> str:
    return "Unavailable" if value is None else f"${value:,.2f}"


def personal_control_embed(status: PersonalExecutionStatus) -> discord.Embed:
    color = AXIS_GREEN if status.connected else 0xD66A6A
    embed = discord.Embed(
        title="💹 AXIS · PERSONAL MOOMOO EXECUTION",
        description=(
            "Owner-only execution control. Member accounts and public signal delivery "
            "are never connected to this module."
        ),
        color=color,
    )
    embed.add_field(
        name="Broker",
        value=("CONNECTED" if status.connected else f"DISCONNECTED · {status.error_code}"),
        inline=True,
    )
    embed.add_field(
        name="Safety Mode",
        value=f"{status.execution_mode} · {status.broker_environment}",
        inline=True,
    )
    embed.add_field(
        name="Owner Account",
        value=f"Equity {_money(status.account_equity)}\nBuying Power {_money(status.buying_power)}",
        inline=True,
    )
    embed.add_field(
        name="Auto Follow",
        value=f"{'ON' if status.auto_follow_enabled else 'OFF'} · {status.follow_scope}",
        inline=True,
    )
    embed.add_field(
        name="Broker Sync",
        value=f"Manual positions {'ON' if status.manual_position_sync_enabled else 'OFF'}",
        inline=True,
    )
    embed.add_field(
        name="Auto Risk",
        value=f"{'ON' if status.auto_risk_management_enabled else 'OFF'}",
        inline=True,
    )
    embed.add_field(
        name="Kill Switches",
        value=(
            f"New entries {'PAUSED' if status.pause_new_entries else 'RUNNING'}\n"
            f"Management {'PAUSED' if status.pause_auto_management else 'RUNNING'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Tracked",
        value=f"Positions {status.active_positions}\nOrders {status.active_orders}",
        inline=True,
    )
    embed.add_field(
        name="Last Reconcile",
        value=(
            status.last_reconciled_at.strftime("%Y-%m-%d %H:%M UTC")
            if status.last_reconciled_at
            else "Never"
        ),
        inline=True,
    )
    embed.set_footer(text="AXIS Owner Only · LIMIT orders only · broker is source of truth")
    return embed


def positions_embed(rows: tuple[PositionView, ...]) -> discord.Embed:
    embed = discord.Embed(title="PERSONAL POSITIONS", color=QUIET_BLACK)
    if not rows:
        embed.description = "No synchronized personal positions."
    for item in rows[:12]:
        pnl = "—" if item.return_pct is None else f"{item.return_pct:+.2f}%"
        cost = "—" if item.average_cost is None else f"${item.average_cost}"
        price = "—" if item.current_price is None else f"${item.current_price}"
        embed.add_field(
            name=f"{item.contract_code} · {item.quantity} contract(s)",
            value=(
                f"Cost {cost} · Current {price} · {pnl}\n"
                f"{item.status} · {item.risk_stage} · {item.source}"
            ),
            inline=False,
        )
    return embed


def orders_embed(rows: tuple[OrderView, ...]) -> discord.Embed:
    embed = discord.Embed(title="PERSONAL ORDERS", color=QUIET_BLACK)
    if not rows:
        embed.description = "No personal execution orders."
    for item in rows[:12]:
        embed.add_field(
            name=f"{item.side} · {item.contract_code}",
            value=(
                f"{item.quantity} @ ${item.limit_price} · {item.purpose}\n"
                f"{item.status} · {item.created_at:%Y-%m-%d %H:%M UTC}"
            ),
            inline=False,
        )
    return embed


def event_embed(event_type: str, payload: dict[str, object]) -> discord.Embed:
    embed = discord.Embed(title=f"AXIS PERSONAL EXECUTION · {event_type}", color=AXIS_GREEN)
    for key, value in list(payload.items())[:8]:
        if "account" in key.lower():
            continue
        embed.add_field(name=key.replace("_", " ").title(), value=str(value)[:1024], inline=False)
    return embed
