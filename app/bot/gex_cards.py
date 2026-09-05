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
    if magnitude >= 1_000_000_000:
        return f"{value / 1_000_000_000:+.2f}B"
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:+.2f}M"
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
        title=f"AXIS GEX EXPLORER · {snapshot.ticker}",
        description="**TEST MODE · Owner-only · card-testing**",
        color=color,
    )
    embed.add_field(name="Spot", value=_money(snapshot.spot), inline=True)
    embed.add_field(name="Gamma Regime", value=snapshot.gamma_regime, inline=True)
    embed.add_field(name="Structural Bias", value=snapshot.current_bias, inline=True)
    embed.add_field(
        name="Aggregate Structure",
        value=(
            f"Net GEX {_gex(snapshot.net_gex)}\n"
            f"Positive GEX {_gex(snapshot.positive_gex)}\n"
            f"Negative GEX {_gex(snapshot.negative_gex)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Key Levels",
        value=(
            f"Zero Gamma {_money(snapshot.zero_gamma)}\n"
            f"Call Wall {_money(snapshot.call_wall)}\n"
            f"Put Wall {_money(snapshot.put_wall)}"
        ),
        inline=True,
    )
    positive_key = snapshot.positive_zones[0] if snapshot.positive_zones else None
    negative_key = snapshot.negative_zones[0] if snapshot.negative_zones else None
    embed.add_field(
        name="Key GEX Zone",
        value=(
            f"Positive {_money(positive_key.peak if positive_key else None)}\n"
            f"Negative {_money(negative_key.peak if negative_key else None)}"
        ),
        inline=True,
    )
    near_label = (
        "0DTE Structure"
        if snapshot.near_term_expiration == snapshot.timestamp_et.astimezone(ET).date()
        else "Near-Term Structure"
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
            f"Near-Term Net GEX {_gex(snapshot.near_term_net_gex)}"
        ),
        inline=True,
    )
    embed.add_field(
        name="Positive GEX Clusters", value=_zones(snapshot.positive_zones), inline=True
    )
    embed.add_field(name="Negative GEX Zones", value=_zones(snapshot.negative_zones), inline=True)
    embed.add_field(
        name="Deterministic Triggers",
        value=f"向上：{snapshot.bullish.description}\n向下：{snapshot.bearish.description}",
        inline=False,
    )
    embed.add_field(
        name="AXIS Structure Read",
        value="\n".join(f"• {line}" for line in snapshot.analysis_zh),
        inline=False,
    )
    states = []
    if result.market_status == "closed":
        states.append("MARKET CLOSED · based on latest available snapshot")
    if result.stale:
        states.append("⚠️ STALE DATA")
    if result.failed_expirations:
        states.append(f"部分到期日已跳过：{len(result.failed_expirations)}")
    if snapshot.data_warnings:
        states.extend(snapshot.data_warnings[:2])
    if states:
        embed.add_field(name="Data Status", value="\n".join(states), inline=False)
    source_time = result.source_timestamp.astimezone(ET).strftime("%m/%d %H:%M:%S ET")
    embed.add_field(
        name="Data / Coverage",
        value=(
            f"Provider {result.provider.title()} · {source_time}\n"
            f"Expirations {result.used_expirations}/10 valid · "
            f"candidates {result.candidate_expirations}\n"
            f"Cache {'HIT' if result.cache_hit else 'MISS'} · policy {result.policy_version} · "
            f"{result.latency_ms}ms"
        ),
        inline=False,
    )
    embed.set_image(url=f"attachment://axis-gex-{snapshot.ticker.lower()}.png")
    embed.set_footer(
        text=(
            "AXIS GEX Explorer · Test Mode · 教育与结构研究用途，不构成投资建议 · "
            "Call 正/Put 负 dealer-gamma 估算，并非真实持仓"
        )
    )
    return embed
