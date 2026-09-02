from __future__ import annotations

import uuid
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.bot.cards import build_short_term_tracking_embed
from app.bot.cogs.card_testing import (
    _analysis_card,
    _preview_offers,
    _short_term_tracking_card,
    _trade_card,
)
from app.bot.cogs.general_control import (
    MembershipView,
)
from app.bot.cogs.newcomer_access import (
    ApplicationFormView,
    ApplyAccessView,
    JoinReviewView,
    RiskAgreementView,
    SafetyAgreementView,
    risk_acknowledgement_embed,
    safety_agreement_embed,
    welcome_application_embed,
)
from app.bot.cogs.short_term_tracking import _same_public_event_embed
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
    assert "https://discord.com/channels/1543309921066684567/" not in welcome
    assert "START HERE" not in welcome
    assert "NO ACCESS" not in welcome
    assert "complete a short access application" in welcome
    assert "3 U.S. TRADING DAYS OF FULL MEMBER ACCESS" in welcome
    assert "No credit card required" in welcome
    assert "No automatic renewal" in welcome
    assert "⚡ Short-Term" in welcome
    assert "〽️ Swing" in welcome
    assert "♾️ LEAPS" in welcome
    assert "🛋️ Member Lounge" in welcome
    assert "MY RISK IS NOT YOUR RISK" in welcome
    assert "AXIS staff will never DM you first" in welcome
    assert "signal-input" not in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$9.99" in subscription
    assert "$99.99" in subscription
    assert "Auto-renews monthly until canceled" in subscription
    assert "3 U.S. Trading Days" in subscription
    assert "1 Trading Day" in subscription
    assert "3 Trading Days" not in subscription
    assert "No card required. No automatic renewal." in subscription
    assert "Free Trial：申请获批后自动开始，共 3 个美国股票市场交易日" in subscription
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
    assert "START FREE TRIAL" not in labels
    assert labels[:2] == ["DAY PASS · $9.99", "MONTHLY · $99.99"]
    assert "MANAGE MEMBERSHIP" in labels

    welcome_view = ApplyAccessView(SimpleNamespace())
    welcome_labels = [item.label for item in welcome_view.children]
    assert welcome_labels == ["APPLY TO JOIN AXIS"]
    assert welcome_view.children[0].custom_id == "axis:newcomer:apply:v1"
    assert welcome_view.children[0].url is None
    assert "MY RISK IS NOT YOUR RISK" in str(risk_acknowledgement_embed().to_dict())
    assert "impersonate AXIS staff" in str(safety_agreement_embed().to_dict())
    assert "APPLY FOR MEMBER ACCESS" not in str(welcome_application_embed().to_dict())


@pytest.mark.asyncio
async def test_welcome_apply_button_enters_application_flow() -> None:
    calls: list[object] = []

    async def begin_application(interaction: object) -> None:
        calls.append(interaction)

    controller = SimpleNamespace(begin_application=begin_application)
    view = ApplyAccessView(controller)
    interaction = object()
    await view.apply(interaction)
    assert calls == [interaction]


def test_application_ui_uses_final_english_questions_agreements_and_review_actions() -> None:
    controller = SimpleNamespace()
    form = ApplicationFormView(controller, 123)
    assert form.children[0].placeholder == "How did you hear about AXIS?"
    assert [option.label for option in form.children[0].options] == [
        "Friend / Referral",
        "X / Social Media",
        "Discord",
        "Online Community",
        "Other",
    ]
    assert form.children[1].placeholder == "What are you mainly interested in?"
    assert [option.label for option in form.children[1].options] == [
        "Short-Term",
        "Swing",
        "LEAPS",
        "Market Analysis",
    ]
    answers = form.answers
    assert [item.label for item in RiskAgreementView(controller, 123, answers).children] == [
        "I AGREE"
    ]
    assert [item.label for item in SafetyAgreementView(controller, 123, answers).children] == [
        "I AGREE"
    ]
    review = JoinReviewView(controller, uuid.uuid4(), status="PENDING")
    assert [item.label for item in review.children] == ["APPROVE", "REJECT", "FLAG"]


def test_card_testing_previews_are_pure_dtos() -> None:
    for action in ("ENTRY", "ADD", "TP1", "RUNNER", "CLOSE"):
        card = _trade_card(action)
        assert card.public_trade_id == "TEST-0001"
        assert card.action == action
    analysis = _analysis_card()
    assert analysis.analysis_code == "TEST-A-0001"
    assert "不写入数据库" in (analysis.summary or "")


def test_short_term_event_id_is_not_member_visible() -> None:
    embed = build_short_term_tracking_embed(
        _short_term_tracking_card("TP"),
        public_ref="STE-26CFC5C8DA92",
    )
    rendered = str(embed.to_dict())

    assert embed.footer.text == "AXIS"
    assert "STE-26CFC5C8DA92" not in rendered
    assert "AXIS Short-Term Event" not in rendered


def test_short_term_event_dedupe_ignores_footer_but_not_content() -> None:
    card = _short_term_tracking_card("TP")
    expected = build_short_term_tracking_embed(card, public_ref="STE-NEW")
    legacy = build_short_term_tracking_embed(card)
    legacy.set_footer(text="AXIS Short-Term Event · STE-OLD")
    different = build_short_term_tracking_embed(replace(card, price=Decimal("9.99")))

    assert _same_public_event_embed(legacy, expected)
    assert not _same_public_event_embed(different, expected)


def test_short_term_risk_notice_is_stable_and_member_safe() -> None:
    text = str(short_term_risk_notice_embed().to_dict())
    assert "MY RISK IS NOT YOUR RISK" in text
    assert "Risk management is personal" in text
    assert "实际仓位、风险管理与退出由每位会员自行决定" in text
    assert "不构成投资或买卖建议" in text
