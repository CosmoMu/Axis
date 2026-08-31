from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.bot.cogs.card_testing import _analysis_card, _preview_offers, _trade_card
from app.bot.cogs.general_control import GeneralControlCog, MembershipView
from app.bot.general_cards import (
    lobby_guide_embed,
    member_wins_guide_embed,
    results_guide_embed,
    short_term_risk_notice_embed,
    subscription_embed,
    welcome_embed,
)


def test_general_cards_are_minimal_single_membership_and_correctly_scoped() -> None:
    welcome = str(
        welcome_embed(
            1543309921066684567,
            {
                "subscriptions": 1543397032188968980,
                "official_results": 1543397033094684782,
                "lobby": 1543397034151641158,
                "member_wins": 1543397035598676184,
                "short_term_alerts": 1543397037511417947,
                "swing_alerts": 1543397038610186251,
                "leaps_alerts": 1543397039872802816,
                "member_chat": 1543397040547958902,
            },
        ).to_dict()
    )
    subscription = str(subscription_embed(_preview_offers()).to_dict())
    results = str(results_guide_embed().to_dict())
    lobby = str(lobby_guide_embed().to_dict())
    wins = str(member_wins_guide_embed().to_dict())

    assert "Signals without the noise" in welcome
    assert "https://discord.com/channels/1543309921066684567/" in welcome
    assert "NO ACCESS" in welcome
    assert "7 个自然日" in welcome
    assert "无需信用卡" in welcome
    assert "不会自动续费" in welcome
    assert "signal-input" not in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$9.99" in subscription
    assert "$99.99" in subscription
    assert "Auto-renews monthly until canceled" in subscription
    assert "7 Calendar Days" in subscription
    assert "1 Trading Day" in subscription
    assert "3 Trading Days" not in subscription
    assert "Free Trial：领取后连续 7 个自然日" in subscription
    for forbidden in ("Basic", "Premium", "VIP", "Stripe", "Whop"):
        assert forbidden not in subscription
    assert "System-tracked" in results
    assert "Past performance" in results
    assert "Open community discussion" in lobby
    assert "not included" in wins
    assert "thumbnail" not in welcome
    assert "footer" not in welcome

    membership_view = MembershipView(
        SimpleNamespace(free_trial_enabled=True),
        _preview_offers(),
    )
    labels = [item.label for item in membership_view.children]
    assert "START FREE TRIAL" in labels
    assert "MANAGE MEMBERSHIP" in labels


def test_card_testing_previews_are_pure_dtos() -> None:
    for action in ("ENTRY", "ADD", "TP1", "RUNNER", "CLOSE"):
        card = _trade_card(action)
        assert card.public_trade_id == "TEST-0001"
        assert card.action == action
    analysis = _analysis_card()
    assert analysis.analysis_code == "TEST-A-0001"
    assert "不写入数据库" in (analysis.summary or "")


def test_short_term_risk_notice_is_stable_and_member_safe() -> None:
    text = str(short_term_risk_notice_embed().to_dict())
    assert "MY RISK IS NOT YOUR RISK" in text
    assert "Risk management is personal" in text
    assert "实际仓位、风险管理与退出由每位会员自行决定" in text
    assert "不构成投资或买卖建议" in text


@pytest.mark.asyncio
async def test_new_member_listener_inspects_eligibility_without_granting_or_dm() -> None:
    class InspectOnlyAccess:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int]] = []

        async def free_trial_claim_state(self, guild_id: int, user_id: int) -> str:
            self.calls.append((guild_id, user_id))
            return "ELIGIBLE"

    class NoDmMember:
        bot = False
        id = 456
        guild = SimpleNamespace(id=123)

        async def send(self, _: str) -> None:
            raise AssertionError("DM must remain disabled")

    access = InspectOnlyAccess()
    controller = SimpleNamespace(
        guild_id=123,
        welcome_channel_id=789,
        free_trial_auto_offer=True,
        free_trial_dm_enabled=False,
        free_trial_calendar_days=7,
        access_service=access,
    )
    await GeneralControlCog.on_member_join(controller, NoDmMember())
    assert access.calls == [(123, 456)]
