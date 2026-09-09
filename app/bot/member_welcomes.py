from __future__ import annotations


def community_welcome_message(user_id: int) -> str:
    return f"🎉 欢迎 <@{user_id}> 加入 AXIS！欢迎在公共交流区和大家打个招呼。"


def member_lounge_welcome_message(
    user_id: int,
    *,
    short_term_channel_id: int,
    swing_channel_id: int,
    leaps_channel_id: int,
) -> str:
    return (
        f"✦ 欢迎 <@{user_id}> 正式进入 AXIS 会员交流区。\n"
        "会员权限现已开启。保持独立判断，尊重风险，尊重市场。\n\n"
        "**会员频道**\n"
        f"⚡ 短线 · <#{short_term_channel_id}>\n"
        f"〽️ 波段 · <#{swing_channel_id}>\n"
        f"♾️ 长期 · <#{leaps_channel_id}>\n\n"
        "🧭 GEX Explorer · 使用 `/gex ticker:SPY` 查看当日 Gamma 支撑、压力与加速区。\n"
        "📈 Stock Analyst · 使用 `/stock ticker:SPY` 查看日 K 结构、关键点位与情景分析。"
    )
