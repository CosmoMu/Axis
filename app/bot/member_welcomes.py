from __future__ import annotations


def community_welcome_message(user_id: int) -> str:
    return f"🎉 欢迎 <@{user_id}> 加入 AXIS！欢迎在 Lobby 和大家打个招呼。"


def member_lounge_welcome_message(
    user_id: int,
    *,
    short_term_channel_id: int,
    swing_channel_id: int,
    leaps_channel_id: int,
) -> str:
    return (
        f"✦ 欢迎 <@{user_id}> 正式进入 AXIS Member Lounge。\n"
        "会员权限现已开启。保持独立判断，尊重风险，尊重市场。\n\n"
        "**MEMBER CHANNELS · 会员频道**\n"
        f"⚡ Short-Term · <#{short_term_channel_id}>\n"
        f"〽️ Swing · <#{swing_channel_id}>\n"
        f"♾️ LEAPS · <#{leaps_channel_id}>\n\n"
        "🧭 GEX Explorer · 在本频道使用 `/gex ticker:SPY`，"
        "查看当日 Gamma 支撑、压力与加速区。"
    )
