from __future__ import annotations

import discord

AXIS_GREEN = 0x86F7A8
QUIET_BLACK = 0x111411


def welcome_embed(*, icon_url: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="AXIS",
        description="**Signals without the noise.**\n\n一个会员，完整访问。",
        color=AXIS_GREEN,
    )
    embed.add_field(
        name="⚡ Short-Term",
        value="短周期交易机会与实时仓位更新",
        inline=False,
    )
    embed.add_field(name="〽️ Swing", value="数日到数周的波段交易机会", inline=False)
    embed.add_field(name="♾️ LEAPS", value="更长期的交易布局与机会", inline=False)
    embed.add_field(
        name="会员权益",
        value=(
            "• 实时交易信号\n"
            "• 入场与加仓更新\n"
            "• TP / SL / 尾仓更新\n"
            "• 当前持仓查看\n"
            "• 市场与个股观点\n"
            "• Member Lounge\n"
            "• 官方历史战绩"
        ),
        inline=False,
    )
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.set_footer(text="AXIS Welcome v1")
    return embed


def subscription_embed(price_display: str, *, icon_url: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title="AXIS MEMBERSHIP",
        description=f"一个会员。\n全部访问。\n\n**{price_display}**",
        color=AXIS_GREEN,
    )
    embed.add_field(
        name="包含",
        value=(
            "⚡ Short-Term\n"
            "〽️ Swing\n"
            "♾️ LEAPS\n"
            "🛋️ Member Lounge\n"
            "Market Analysis\n"
            "Ticker Analysis\n"
            "Active Trade View\n"
            "Official Results"
        ),
        inline=False,
    )
    if icon_url:
        embed.set_thumbnail(url=icon_url)
    embed.set_footer(text="AXIS Membership v1")
    return embed


def results_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="AXIS Results",
        description="这里只展示 AXIS 系统记录的官方已关闭订单结果。",
        color=QUIET_BLACK,
    )
    embed.set_footer(text="AXIS Results Guide v1")
    return embed


def lobby_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="AXIS Lobby",
        description="公开市场讨论、新用户问题、产品功能与社区交流。",
        color=QUIET_BLACK,
    )
    embed.add_field(
        name="频道边界",
        value="Signal、Analysis 与官方 Results 不会自动发布到这里。",
        inline=False,
    )
    embed.set_footer(text="AXIS Lobby Guide v1")
    return embed


def member_wins_guide_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Community-submitted results.",
        description=(
            "这些结果由会员自行提交，不属于 AXIS 官方统计战绩。\n\n"
            "官方结果请查看：<#RESULTS_CHANNEL_ID>"
        ),
        color=QUIET_BLACK,
    )
    embed.set_footer(text="AXIS Member Wins Guide v1")
    return embed
