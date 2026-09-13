"""Discord presentation for the AXIS SPXW 0DTE Desk."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import discord

from app.services.spxw_0dte_desk import SpxwCapabilityReport

ET = ZoneInfo("America/New_York")


def build_spxw_capability_embed(report: SpxwCapabilityReport) -> discord.Embed:
    status = "能力门禁通过" if report.ready else "失败关闭"
    color = 0x86F7A8 if report.ready else 0xE6C84F
    embed = discord.Embed(
        title="AXIS · SPXW 0DTE",
        description=("**测试模式 · Moomoo Only**\n市场已收盘 · 使用最新可验证的 Moomoo 能力数据"),
        color=color,
    )
    embed.add_field(name="运行状态", value=status, inline=True)
    embed.add_field(name="期权系列", value="SPXW · 0DTE Only", inline=True)
    embed.add_field(name="数据源", value="Moomoo OpenD", inline=True)
    embed.add_field(
        name="SPXW 期权数据",
        value=(
            f"合约链 {'✓' if report.spxw_chain and report.spxw_only else '×'} · "
            f"{report.contract_count} 张\n"
            f"Gamma / IV / OI / 成交量 "
            f"{'✓' if _option_fields_ready(report) else '×'}\n"
            f"Bid / Ask / 时间戳 {'✓' if report.bid_ask and report.timestamps else '×'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="指数基准数据",
        value=(
            f"SPX 现价 {'✓' if report.spx_spot else '× Moomoo 当前不支持'}\n"
            f"SPX 5 分钟 K 线 {'✓' if report.spx_5m else '× Moomoo 当前不支持'}"
        ),
        inline=False,
    )
    if not report.ready:
        embed.add_field(
            name="安全处理",
            value=(
                "未生成评分、方向或关键点位。\n未使用 SPY、行权价推算、缓存假值或 Massive 兜底。"
            ),
            inline=False,
        )
    checked = report.checked_at.astimezone(ET).strftime("%m/%d %H:%M:%S ET")
    embed.add_field(
        name="验证信息",
        value=(
            f"链日期 {report.chain_session:%Y-%m-%d}\n"
            f"验证时间 {checked}\n"
            f"错误码 {report.error_code or '—'}"
        ),
        inline=False,
    )
    embed.set_image(url="attachment://axis-spxw-0dte-test.png")
    embed.set_footer(
        text=(
            "仅用于市场分析与教育。 不构成投资建议、交易建议或买卖信号。 MY RISK IS NOT YOUR RISK."
        )
    )
    return embed


def _option_fields_ready(report: SpxwCapabilityReport) -> bool:
    return all((report.gamma, report.implied_volatility, report.open_interest, report.volume))
