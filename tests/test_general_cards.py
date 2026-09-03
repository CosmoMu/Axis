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
    ReferralModal,
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
from app.bot.member_welcomes import community_welcome_message, member_lounge_welcome_message


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

    assert "👋 欢迎来到 AXIS" in welcome
    assert "这里只是 AXIS 欢迎界面" in welcome
    assert "看到这个页面并不代表你已经加入 AXIS" in welcome
    assert "申请加入 AXIS" in welcome
    assert "如需加入，请点击下方绿色" in welcome
    assert "https://discord.com/channels/1543309921066684567/" not in welcome
    assert "START HERE" not in welcome
    assert "NO ACCESS" not in welcome
    assert "填写简短的加入申请" in welcome
    assert "3 个美国股票市场交易日" in welcome
    assert "无需信用卡，不会自动续费" in welcome
    assert "⚡ 短线" in welcome
    assert "〽️ 波段" in welcome
    assert "♾️ 长期" in welcome
    assert "🛋️ 会员交流区" in welcome
    assert "请独立判断并自行承担风险" in welcome
    assert "AXIS 工作人员绝不会主动私信" in welcome
    for forbidden_english in (
        "WELCOME TO AXIS",
        "THIS IS THE AXIS WELCOME PAGE",
        "APPLY TO JOIN AXIS",
        "HOW TO JOIN",
        "AFTER APPROVAL",
        "RISK NOTICE",
        "SAFETY NOTICE",
    ):
        assert forbidden_english not in welcome
    assert "signal-input" not in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$9.99" in subscription
    assert "$149.99" in subscription
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
    assert labels[:2] == ["DAY PASS · $9.99", "MONTHLY · $149.99"]
    assert "MANAGE MEMBERSHIP" in labels

    welcome_view = ApplyAccessView(SimpleNamespace())
    welcome_labels = [item.label for item in welcome_view.children]
    assert welcome_labels == ["申请加入 AXIS"]
    assert welcome_view.children[0].custom_id == "axis:newcomer:apply:v1"
    assert welcome_view.children[0].url is None
    assert "我的风险不等于你的风险" in str(risk_acknowledgement_embed().to_dict())
    assert "冒充 AXIS 工作人员" in str(safety_agreement_embed().to_dict())
    application_welcome = str(welcome_application_embed().to_dict())
    assert "APPLY FOR MEMBER ACCESS" not in application_welcome
    assert "这里只是 AXIS 欢迎界面" in application_welcome
    assert "申请加入 AXIS" in application_welcome
    assert "APPLY TO JOIN AXIS" not in application_welcome
    assert "AXIS Welcome" not in application_welcome


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


def test_application_ui_uses_chinese_questions_agreements_and_review_actions() -> None:
    controller = SimpleNamespace()
    form = ApplicationFormView(controller, 123)
    assert form.children[0].placeholder == "你是通过什么渠道了解到 AXIS 的？"
    assert [option.label for option in form.children[0].options] == [
        "朋友推荐",
        "X / 社交媒体",
        "Discord",
        "网络社区",
        "其他",
    ]
    assert form.children[1].placeholder == "你主要对哪些内容感兴趣？"
    assert [option.label for option in form.children[1].options] == [
        "短线",
        "波段",
        "长期",
        "市场分析",
    ]
    assert form.children[2].label == "继续"
    answers = form.answers
    referral = ReferralModal(controller, 123, answers)
    assert referral.title == "AXIS 加入申请"
    assert referral.referred_by.label == "谁推荐你加入 AXIS？（选填）"
    assert referral.referred_by.placeholder == "可填写 Discord 用户名、昵称或推荐人名称"
    assert [item.label for item in RiskAgreementView(controller, 123, answers).children] == [
        "我已阅读并同意"
    ]
    assert [item.label for item in SafetyAgreementView(controller, 123, answers).children] == [
        "我已阅读并同意"
    ]
    review = JoinReviewView(controller, uuid.uuid4(), status="PENDING")
    assert [item.label for item in review.children] == ["批准", "拒绝", "标记"]


def test_approval_welcomes_mention_the_member_in_both_destinations() -> None:
    lobby = community_welcome_message(123)
    member_lounge = member_lounge_welcome_message(
        123,
        short_term_channel_id=201,
        swing_channel_id=202,
        leaps_channel_id=203,
    )

    assert "<@123>" in lobby
    assert "Lobby" in lobby
    assert "<@123>" in member_lounge
    assert "Member Lounge" in member_lounge
    assert "保持独立判断" in member_lounge
    assert "尊重风险，尊重市场" in member_lounge
    assert "⚡ Short-Term · <#201>" in member_lounge
    assert "〽️ Swing · <#202>" in member_lounge
    assert "♾️ LEAPS · <#203>" in member_lounge


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
