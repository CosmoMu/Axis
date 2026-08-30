from __future__ import annotations

from collections.abc import Mapping

import discord

from app.services.membership_access import PriceSnapshot

AXIS_GREEN = 0x86F7A8
QUIET_BLACK = 0x111411


def welcome_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS",
        description=(
            "**Signals without the noise.**\n\n"
            "清晰的交易信号。\n"
            "统一的仓位管理。\n"
            "没有多余噪音。\n\n"
            "**SHORT-TERM · SWING · LEAPS**"
        ),
        color=AXIS_GREEN,
    )


def subscription_embed(offers: Mapping[str, PriceSnapshot]) -> discord.Embed:
    day_pass = offers.get("DAY_PASS")
    monthly = offers.get("MONTHLY")
    day_price = day_pass.display_amount if day_pass else "Unavailable"
    monthly_price = monthly.display_amount if monthly else "Unavailable"
    embed = discord.Embed(
        title="AXIS MEMBERSHIP",
        description="**One membership. Full access.**",
        color=AXIS_GREEN,
    )
    embed.add_field(
        name="FREE TRIAL",
        value="3 Trading Days\n$0\n\nNo card required.",
        inline=True,
    )
    embed.add_field(
        name="DAY PASS",
        value=f"1 Trading Day\n{day_price}\n\nOne-time payment.",
        inline=True,
    )
    embed.add_field(
        name="MONTHLY",
        value=f"{monthly_price} / month\n\nRecurring monthly.\nCancel anytime.",
        inline=True,
    )
    embed.add_field(
        name="ACCESS INCLUDES",
        value=("Short-Term · Swing · LEAPS\nMarket Analysis · Active Positions · Member Lounge"),
        inline=False,
    )
    embed.add_field(
        name="TRADING DAYS",
        value="U.S. market calendar. Weekends and market holidays do not count.",
        inline=False,
    )
    embed.add_field(
        name="NOTICE",
        value="仅供市场分析与教育交流，不构成投资或买卖建议。交易存在风险。",
        inline=False,
    )
    return embed


def risk_disclosure_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS MEMBERSHIP NOTICE",
        description=(
            "AXIS 提供的内容仅用于市场分析、研究和教育交流，不构成投资建议、财务建议、"
            "交易建议或任何证券买卖建议。\n\n"
            "所有交易观点、信号、价格区间、SL、TP、市场分析和历史数据均仅供参考。\n\n"
            "金融市场尤其是期权交易存在重大风险，可能导致部分或全部本金损失。"
            "过去表现不代表未来结果。\n\n"
            "用户应根据自身情况独立判断并自行承担所有交易风险。\n\n"
            "AXIS 不管理会员资金，不代表会员执行交易，不提供针对个人财务状况的"
            "个性化投资建议。"
        ),
        color=QUIET_BLACK,
    )


def results_guide_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS RESULTS",
        description=(
            "System-tracked completed trades.\n\n"
            "Past performance does not guarantee future results."
        ),
        color=QUIET_BLACK,
    )


def lobby_guide_embed() -> discord.Embed:
    """Preview-only DTO. Lobby itself intentionally receives no automatic message."""
    return discord.Embed(
        title="AXIS LOBBY",
        description="Open community discussion for markets, AXIS, and general questions.",
        color=QUIET_BLACK,
    )


def member_wins_guide_embed() -> discord.Embed:
    return discord.Embed(
        title="COMMUNITY WINS",
        description=(
            "Member-submitted trades and results.\n\n"
            "Community submissions are not included in official AXIS performance statistics.\n\n"
            "Past performance does not guarantee future results."
        ),
        color=QUIET_BLACK,
    )
