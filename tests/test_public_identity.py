from __future__ import annotations

import pytest

from app.bot.cards import build_public_analysis_embed, build_public_trade_embed
from app.bot.cogs.card_testing import _analysis_card, _preview_offers, _trade_card
from app.bot.general_cards import (
    member_wins_guide_embed,
    results_guide_embed,
    risk_disclosure_embed,
    subscription_embed,
    welcome_embed,
)
from app.domain.public_identity import PublicIdentityPolicy, PublicIdentityViolation


def test_every_public_general_and_preview_card_passes_identity_policy() -> None:
    policy = PublicIdentityPolicy(operator_name="VALE", owner_user_id=999999999999999999)
    cards = [
        welcome_embed(),
        subscription_embed(_preview_offers()),
        risk_disclosure_embed(),
        results_guide_embed(),
        member_wins_guide_embed(),
        build_public_trade_embed(_trade_card("ENTRY")),
        build_public_analysis_embed(_analysis_card(), public_ref="TEST"),
    ]
    for card in cards:
        policy.assert_public(card.to_dict())


@pytest.mark.parametrize(
    "payload",
    [
        {"description": "Cosmos private note"},
        {"description": "Contact <@999999999999999999>"},
        {"description": "owner 999999999999999999"},
        {"description": "AXIS" + " DESK"},
    ],
)
def test_public_identity_policy_rejects_private_identity(payload: dict[str, str]) -> None:
    policy = PublicIdentityPolicy(owner_user_id=999999999999999999)
    with pytest.raises(PublicIdentityViolation):
        policy.assert_public(payload)
