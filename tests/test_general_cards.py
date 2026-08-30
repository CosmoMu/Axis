from __future__ import annotations

from app.bot.cogs.card_testing import _analysis_card, _preview_offers, _trade_card
from app.bot.general_cards import (
    lobby_guide_embed,
    member_wins_guide_embed,
    results_guide_embed,
    subscription_embed,
    welcome_embed,
)


def test_general_cards_are_minimal_single_membership_and_correctly_scoped() -> None:
    welcome = str(welcome_embed().to_dict())
    subscription = str(subscription_embed(_preview_offers()).to_dict())
    results = str(results_guide_embed().to_dict())
    lobby = str(lobby_guide_embed().to_dict())
    wins = str(member_wins_guide_embed().to_dict())

    assert "Signals without the noise" in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$9.99" in subscription
    assert "$99.99" in subscription
    for forbidden in ("Basic", "Premium", "VIP", "Stripe", "Whop"):
        assert forbidden not in subscription
    assert "System-tracked" in results
    assert "Past performance" in results
    assert "Open community discussion" in lobby
    assert "not included" in wins
    assert "thumbnail" not in welcome
    assert "footer" not in welcome


def test_card_testing_previews_are_pure_dtos() -> None:
    for action in ("ENTRY", "ADD", "TP1", "RUNNER", "CLOSE"):
        card = _trade_card(action)
        assert card.public_trade_id == "TEST-0001"
        assert card.action == action
    analysis = _analysis_card()
    assert analysis.analysis_code == "TEST-A-0001"
    assert "不写入数据库" in (analysis.summary or "")
