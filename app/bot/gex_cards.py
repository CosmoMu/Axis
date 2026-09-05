"""Discord presentation for AXIS GEX Explorer."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import discord

from app.services.gex_explorer import GexQueryResult

ET = ZoneInfo("America/New_York")


def _money(value: float | None) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _gex(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 100_000_000:
        return f"{value / 100_000_000:+.2f}亿"
    if magnitude >= 10_000:
        return f"{value / 10_000:+.2f}万"
    return f"{value:+,.0f}"


def _zones(zones) -> str:
    if not zones:
        return "—"
    rendered = []
    for zone in zones[:3]:
        level = f"{zone.peak:g}" if zone.lower == zone.upper else f"{zone.lower:g}–{zone.upper:g}"
        rendered.append(f"{level}（峰值 {zone.peak:g}）")
    return "\n".join(rendered)


def build_gex_embed(result: GexQueryResult) -> discord.Embed:
    snapshot = result.snapshot
    color = 0x86F7A8 if snapshot.net_gex >= 0 else 0xD66A6A
    embed = discord.Embed(
        title=f"AXIS GEX · {snapshot.ticker}",
        description="**测试模式 · 仅限所有者 · 卡片测试频道**",
        color=color,
    )
    embed.add_field(name="现价", value=_money(snapshot.spot), inline=True)
    embed.add_field(name="Gamma 状态", value=snapshot.gamma_regime, inline=True)
    embed.add_field(name="结构倾向", value=snapshot.current_bias, inline=True)
    embed.add_field(
        name="整体 GEX 结构",
        value=(
            f"净 GEX {_gex(snapshot.net_gex)}\n"
            f"正 GEX {_gex(snapshot.positive_gex)}\n"
            f"负 GEX {_gex(snapshot.negative_gex)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="关键位置",
        value=(
            f"0 Gamma · Gamma 分界 {_money(snapshot.zero_gamma)}\n"
            f"Call Wall · 大压力 {_money(snapshot.call_wall)}\n"
            f"小压力 {_money(snapshot.minor_resistance)}\n"
            f"Put Wall · 大支撑 {_money(snapshot.put_wall)}\n"
            f"小支撑 {_money(snapshot.minor_support)}"
        ),
        inline=True,
    )
    positive_key = snapshot.positive_zones[0] if snapshot.positive_zones else None
    negative_key = snapshot.negative_zones[0] if snapshot.negative_zones else None
    embed.add_field(
        name="主要 GEX 区域",
        value=(
            f"稳定区 {_money(positive_key.peak if positive_key else None)}\n"
            f"波动加速区 {_money(negative_key.peak if negative_key else None)}"
        ),
        inline=True,
    )
    near_label = (
        "当日到期结构"
        if snapshot.near_term_expiration == snapshot.timestamp_et.astimezone(ET).date()
        else "近期到期结构"
    )
    near_date = (
        snapshot.near_term_expiration.strftime("%m/%d")
        if snapshot.near_term_expiration is not None
        else "—"
    )
    embed.add_field(
        name=near_label,
        value=(
            f"{near_date} · {snapshot.near_term_regime}\n"
            f"近期净 GEX {_gex(snapshot.near_term_net_gex)}"
        ),
        inline=True,
    )
    embed.add_field(name="正 GEX 集中区", value=_zones(snapshot.positive_zones), inline=True)
    embed.add_field(name="负 GEX 加速区", value=_zones(snapshot.negative_zones), inline=True)
    embed.add_field(
        name="结构触发",
        value=f"向上：{snapshot.bullish.description}\n向下：{snapshot.bearish.description}",
        inline=False,
    )
    embed.add_field(
        name="AXIS 结构解读",
        value="\n".join(f"• {line}" for line in snapshot.analysis_zh),
        inline=False,
    )
    states = []
    if result.market_status == "closed":
        states.append("市场已收盘 · 使用最近可用快照")
    if result.stale:
        states.append("⚠️ 数据时间早于实时阈值")
    if result.failed_expirations:
        states.append(f"部分到期日已跳过：{len(result.failed_expirations)}")
    if snapshot.data_warnings:
        states.extend(snapshot.data_warnings[:2])
    if states:
        embed.add_field(name="数据状态", value="\n".join(states), inline=False)
    source_time = result.source_timestamp.astimezone(ET).strftime("%m/%d %H:%M:%S ET")
    intraday_time = result.intraday_source_timestamp.astimezone(ET).strftime("%m/%d %H:%M:%S ET")
    embed.add_field(
        name="数据与覆盖",
        value=(
            f"GEX 数据源 {result.provider.title()} · {source_time}\n"
            f"1 分钟 K 线 {result.intraday_provider.title()} · {intraday_time} · "
            f"{result.intraday_bar_count} 根\n"
            f"有效到期日 {result.used_expirations}/10 · 候选 {result.candidate_expirations}\n"
            f"缓存 {'命中' if result.cache_hit else '未命中'} · 策略 {result.policy_version} · "
            f"{result.latency_ms} 毫秒"
        ),
        inline=False,
    )
    embed.set_image(url=f"attachment://axis-gex-{snapshot.ticker.lower()}.png")
    embed.set_footer(
        text=(
            "AXIS GEX · 测试模式 · 教育与结构研究用途，不构成投资建议 · "
            "正负 Gamma 符号为持仓结构估算，并非真实做市商持仓"
        )
    )
    return embed
