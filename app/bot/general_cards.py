from __future__ import annotations

from collections.abc import Mapping

import discord

from app.services.membership_access import PriceSnapshot

AXIS_GREEN = 0x86F7A8
QUIET_BLACK = 0x111411


def welcome_embed(
    guild_id: int | None = None,
    channel_ids: Mapping[str, int] | None = None,
    *,
    free_trial_trading_days: int = 3,
    free_trial_enabled: bool = True,
) -> discord.Embed:
    del guild_id, channel_ids
    approval_copy = (
        f"自动获得 **{free_trial_trading_days} 个美国股票市场交易日**的完整会员权限。\n\n"
        "无需信用卡，不会自动续费。"
        if free_trial_enabled
        else "新会员申请目前暂时关闭。"
    )

    embed = discord.Embed(
        title="👋 欢迎来到 AXIS",
        description=(
            "**这里只是 AXIS 欢迎界面**\n\n"
            "看到这个页面并不代表你已经加入 AXIS。\n\n"
            "**如需加入，请点击下方绿色「申请加入 AXIS」按钮并提交申请。**"
        ),
        color=AXIS_GREEN,
    )
    embed.add_field(
        name="🚪 如何加入",
        value=(
            "1. 点击下方「申请加入 AXIS」按钮。\n"
            "2. 填写简短的加入申请。\n"
            "3. 提交后等待管理员审核。"
        ),
        inline=False,
    )
    embed.add_field(
        name="🎁 审核通过后",
        value=approval_copy,
        inline=False,
    )
    embed.add_field(
        name="会员权限",
        value="⚡ 短线\n〽️ 波段\n♾️ 长期\n🛋️ 会员交流区",
        inline=False,
    )
    embed.add_field(
        name="风险提示",
        value=(
            "AXIS 仅提供市场研究与教育内容，不构成投资、财务或交易建议。\n"
            "交易存在风险，请独立判断并自行承担风险。"
        ),
        inline=False,
    )
    embed.add_field(
        name="安全提示",
        value=(
            "AXIS 工作人员绝不会主动私信索取私人付款、密码、券商账户信息、"
            "加密货币转账或远程访问权限。"
        ),
        inline=False,
    )
    return embed


def subscription_embed(
    offers: Mapping[str, PriceSnapshot],
    *,
    free_trial_trading_days: int = 3,
    free_trial_enabled: bool = True,
) -> discord.Embed:
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
        value=(
            f"{free_trial_trading_days} U.S. Trading Days\n$0\n\n"
            "No card required. No automatic renewal."
            if free_trial_enabled
            else "Temporarily unavailable."
        ),
        inline=True,
    )
    embed.add_field(
        name="DAY PASS",
        value=f"1 Trading Day\n{day_price}\n\nOne-time payment.",
        inline=True,
    )
    embed.add_field(
        name="MONTHLY",
        value=(f"{monthly_price} / month\n\nAuto-renews monthly until canceled.\nCancel anytime."),
        inline=True,
    )
    embed.add_field(
        name="ACCESS INCLUDES",
        value=("Short-Term · Swing · LEAPS\nMarket Analysis · Active Positions · Member Lounge"),
        inline=False,
    )
    embed.add_field(
        name="HOW TIME IS COUNTED",
        value=(
            f"Free Trial：申请获批后自动开始，共 {free_trial_trading_days} 个美国股票市场交易日，"
            "周末与市场休市日不计入。\n"
            "Day Pass：1 个美国股票市场交易日，周末与市场休市日不计入。"
        ),
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
            "个性化投资建议。\n\n"
            "**MY RISK IS NOT YOUR RISK.**"
        ),
        color=QUIET_BLACK,
    )


def free_trial_used_embed() -> discord.Embed:
    return discord.Embed(
        title="AXIS FREE TRIAL",
        description=("你的免费体验已经使用过。\n\n你可以前往 Membership 页面继续访问 AXIS。"),
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


def short_term_risk_notice_embed() -> discord.Embed:
    return discord.Embed(
        title="RISK NOTICE",
        description=(
            "Risk management is personal.\n\n"
            "AXIS tracks market performance and reference protection levels.\n"
            "Every member is responsible for their own position sizing and exits.\n\n"
            "**MY RISK IS NOT YOUR RISK.**\n\n"
            "AXIS 仅记录市场表现和参考保护位置，\n"
            "实际仓位、风险管理与退出由每位会员自行决定。\n\n"
            "仅供市场分析与教育交流，不构成投资或买卖建议。"
        ),
        color=QUIET_BLACK,
    )
