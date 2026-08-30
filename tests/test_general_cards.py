from __future__ import annotations

from app.bot.cogs.card_testing import _analysis_card, _trade_card
from app.bot.general_cards import (
    lobby_guide_embed,
    member_wins_guide_embed,
    results_guide_embed,
    subscription_embed,
    welcome_embed,
)


def test_general_cards_are_minimal_single_membership_and_correctly_scoped() -> None:
    welcome = str(welcome_embed().to_dict())
    subscription = str(subscription_embed("$XX / month").to_dict())
    results = str(results_guide_embed().to_dict())
    lobby = str(lobby_guide_embed().to_dict())
    wins = str(member_wins_guide_embed().to_dict())

    assert "Signals without the noise" in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$XX / month" in subscription
    for forbidden in ("Basic", "Premium", "VIP", "Stripe", "Whop"):
        assert forbidden not in subscription
    assert "官方" in results
    assert "不会自动发布" in lobby
    assert "不属于 AXIS 官方统计战绩" in wins


def test_card_testing_previews_are_pure_dtos() -> None:
    for action in ("ENTRY", "ADD", "TP1", "RUNNER", "CLOSE"):
        card = _trade_card(action)
        assert card.public_trade_id == "TEST-0001"
        assert card.action == action
    analysis = _analysis_card()
    assert analysis.analysis_code == "TEST-A-0001"
    assert "不写入数据库" in (analysis.summary or "")
