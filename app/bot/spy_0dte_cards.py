"""Discord presentation for the AXIS SPY 0DTE Desk."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import discord

from app.services.spy_0dte_desk import Spy0dteSnapshot, SpyCapabilityReport

ET = ZoneInfo("America/New_York")


def build_spy_capability_embed(report: SpyCapabilityReport) -> discord.Embed:
    status = "能力门禁通过" if report.ready else "失败关闭"
    color = 0x86F7A8 if report.ready else 0xE6C84F
    embed = discord.Embed(
        title="AXIS · SPY 0DTE",
        description=("**测试模式 · Moomoo Only**\n市场已收盘 · 使用最新可验证的 Moomoo 能力数据"),
        color=color,
    )
    embed.add_field(name="运行状态", value=status, inline=True)
    embed.add_field(name="期权系列", value="SPY · 当日到期", inline=True)
    embed.add_field(name="数据源", value="Moomoo OpenD", inline=True)
    embed.add_field(
        name="SPY 基准",
        value=f"现价 ${report.spot:,.2f}" if report.spot is not None else "现价 —",
        inline=True,
    )
    embed.add_field(
        name="SPY 期权数据",
        value=(
            f"合约链 {'✓' if report.spy_chain and report.spy_only else '×'} · "
            f"{report.contract_count} 张\n"
            f"Gamma / IV / OI / 成交量 "
            f"{'✓' if _option_fields_ready(report) else '×'}\n"
            f"Bid / Ask / 时间戳 {'✓' if report.bid_ask and report.timestamps else '×'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="标的基准数据",
        value=(
            f"SPY 现价 {'✓' if report.spy_spot else '× Moomoo 当前不可用'}\n"
            f"SPY 5 分钟 K 线 {'✓' if report.spy_5m else '× Moomoo 当前不可用'} · "
            f"{report.bar_count} 根"
        ),
        inline=False,
    )
    if not report.ready:
        embed.add_field(
            name="安全处理",
            value=(
                "未生成评分、方向或关键点位。\n未使用代理标的、缓存假值或 Massive 兜底。"
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
    embed.set_image(url="attachment://axis-spy-0dte-test.png")
    embed.set_footer(
        text=(
            "仅用于市场分析与教育。 不构成投资建议、交易建议或买卖信号。 MY RISK IS NOT YOUR RISK."
        )
    )
    return embed


def _option_fields_ready(report: SpyCapabilityReport) -> bool:
    return all((report.gamma, report.implied_volatility, report.open_interest, report.volume))


def build_spy_snapshot_embed(snapshot: Spy0dteSnapshot) -> discord.Embed:
    score = f"{snapshot.display_score:+d}"
    color = (
        0x86F7A8
        if snapshot.display_score > 19
        else 0xE56B73
        if snapshot.display_score < -19
        else 0xD9DDD8
    )
    state = "历史收盘测试快照" if snapshot.stale else "实时数据正常"
    embed = discord.Embed(
        title="AXIS · SPY 0DTE",
        description=(
            f"## SPY · ${snapshot.spot:,.2f}\n"
            f"**{snapshot.structure_label}**　`结构评分 {score}`"
        ),
        color=color,
    )
    embed.add_field(
        name="Gamma 结构",
        value=(
            f"环境：{snapshot.gamma_regime}\n"
            f"0DTE Net GEX：{_money(snapshot.net_gex)}\n"
            f"Gamma Flip：{_price(snapshot.gamma_flip)}\n"
            f"Gamma Magnet：{_price(snapshot.gamma_magnet)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="关键位置",
        value=(
            f"支撑：{_levels(snapshot.supports)}\n"
            f"压力：{_levels(snapshot.resistances)}\n"
            f"Call Wall：{_price(snapshot.call_wall)}\n"
            f"Put Wall：{_price(snapshot.put_wall)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="价格结构",
        value=(
            f"VWAP：${snapshot.vwap:,.2f} · {_position(snapshot.spot, snapshot.vwap)}\n"
            f"5分钟 9EMA：${snapshot.ema9_5m:,.2f} · {_position(snapshot.spot, snapshot.ema9_5m)}\n"
            f"成交量：{snapshot.volume_ratio:.2f}× 最近20根均值"
            if snapshot.volume_ratio is not None
            else f"VWAP：${snapshot.vwap:,.2f}\n5分钟 9EMA：${snapshot.ema9_5m:,.2f}\n成交量：—"
        ),
        inline=False,
    )
    embed.add_field(
        name="0DTE Gamma Flow",
        value=(
            f"成交量 Gamma：{snapshot.volume_gamma_bias}\n"
            f"OI Gamma：{snapshot.oi_gamma_bias}\n"
            f"动能：{snapshot.momentum}\n"
            "预期波动："
            f"{f'±${snapshot.expected_move:,.2f}' if snapshot.expected_move is not None else '—'}"
        ),
        inline=True,
    )
    embed.add_field(
        name="数据状态",
        value=(
            f"{state}\n"
            f"交易日：{snapshot.session_date:%Y-%m-%d}\n"
            f"合约：{snapshot.option_contract_count} 张\n"
            f"更新：{snapshot.spot_timestamp.astimezone(ET):%H:%M} ET"
        ),
        inline=True,
    )
    embed.set_image(url="attachment://axis-spy-0dte.png")
    embed.set_footer(
        text="仅用于市场分析与教育。不构成投资建议、交易建议或买卖信号。MY RISK IS NOT YOUR RISK."
    )
    return embed


def _money(value: float) -> str:
    sign = "+" if value >= 0 else "-"
    amount = abs(value)
    if amount >= 1_000_000_000:
        return f"{sign}${amount / 1_000_000_000:.2f}B"
    if amount >= 1_000_000:
        return f"{sign}${amount / 1_000_000:.1f}M"
    return f"{sign}${amount:,.0f}"


def _price(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _levels(values: tuple[float, ...]) -> str:
    return " / ".join(f"${value:,.2f}" for value in values) if values else "—"


def _position(spot: float, reference: float) -> str:
    return "上方" if spot > reference else "下方" if spot < reference else "重合"
