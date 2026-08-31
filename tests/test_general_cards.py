from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.bot.cogs.card_testing import _analysis_card, _preview_offers, _trade_card
from app.bot.cogs.general_control import (
    GeneralControlCog,
    MembershipView,
    RiskDisclosureView,
    WelcomeView,
)
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
    assert "7 天完整会员体验" in welcome
    assert "无需信用卡" in welcome
    assert "不会自动续费" in welcome
    assert "⚡ Short-Term" in welcome
    assert "〽️ Swing" in welcome
    assert "♾️ LEAPS" in welcome
    assert "🛋️ Member Lounge" in welcome
    assert "MY RISK IS NOT YOUR RISK" in welcome
    assert "signal-input" not in welcome
    assert "AXIS MEMBERSHIP" in subscription
    assert "$9.99" in subscription
    assert "$99.99" in subscription
    assert "Auto-renews monthly until canceled" in subscription
    assert "7 Calendar Days" in subscription
    assert "1 Trading Day" in subscription
    assert "3 Trading Days" not in subscription
    assert "No card required. No automatic renewal." in subscription
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

    welcome_view = WelcomeView(
        SimpleNamespace(
            free_trial_enabled=True,
            free_trial_calendar_days=7,
            guild_id=1543309921066684567,
            subscriptions_channel_id=1543397032188968980,
        )
    )
    welcome_labels = [item.label for item in welcome_view.children]
    assert welcome_labels == ["START 7-DAY FREE TRIAL", "VIEW MEMBERSHIP"]
    assert welcome_view.children[0].custom_id == "axis:welcome:free_trial:v1"
    assert welcome_view.children[0].url is None
    assert welcome_view.children[1].url == (
        "https://discord.com/channels/1543309921066684567/1543397032188968980"
    )

    risk_view = RiskDisclosureView(SimpleNamespace(), "FREE_TRIAL")
    assert [item.label for item in risk_view.children] == ["I UNDERSTAND"]


@pytest.mark.asyncio
async def test_welcome_trial_button_enters_free_trial_interaction_flow() -> None:
    calls: list[tuple[object, str]] = []

    async def request_plan(interaction: object, plan_type: str) -> None:
        calls.append((interaction, plan_type))

    controller = SimpleNamespace(
        free_trial_enabled=True,
        free_trial_calendar_days=7,
        guild_id=123,
        subscriptions_channel_id=789,
        request_plan=request_plan,
    )
    view = WelcomeView(controller)
    interaction = object()
    await view.free_trial(interaction)
    assert calls == [(interaction, "FREE_TRIAL")]


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


class FakeInteractionResponse:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}
        self.deferred = False

    async def send_message(self, *args: object, **kwargs: object) -> None:
        self.payload = {"args": args, **kwargs}

    async def defer(self, *, ephemeral: bool) -> None:
        self.deferred = ephemeral


class FakeFollowup:
    def __init__(self) -> None:
        self.payload: dict[str, object] = {}

    async def send(self, *args: object, **kwargs: object) -> None:
        self.payload = {"args": args, **kwargs}


class FakeInteraction:
    guild_id = 123
    id = 999
    user = SimpleNamespace(id=456)

    def __init__(self) -> None:
        self.response = FakeInteractionResponse()
        self.followup = FakeFollowup()


@pytest.mark.asyncio
async def test_welcome_trial_used_and_active_access_responses_do_not_claim() -> None:
    class StateOnlyAccess:
        def __init__(self, state: str) -> None:
            self.state = state

        async def free_trial_claim_state(self, *_: object) -> str:
            return self.state

    controller = object.__new__(GeneralControlCog)
    controller.guild_id = 123
    controller.subscriptions_channel_id = 789

    controller.access_service = StateOnlyAccess("USED")
    used = FakeInteraction()
    await controller.request_plan(used, "FREE_TRIAL")
    used_embed = used.response.payload["embed"]
    assert used_embed.title == "AXIS FREE TRIAL"
    assert "已经使用过" in used_embed.description
    used_view = used.response.payload["view"]
    assert [item.label for item in used_view.children] == ["VIEW MEMBERSHIP"]

    controller.access_service = StateOnlyAccess("ACCESS_ACTIVE")
    active = FakeInteraction()
    await controller.request_plan(active, "FREE_TRIAL")
    assert active.response.payload["args"] == (
        "You already have active AXIS member access.",
    )


@pytest.mark.asyncio
async def test_trial_activation_uses_access_service_and_syncs_role_without_stripe() -> None:
    started_at = datetime(2026, 8, 31, 15, tzinfo=UTC)

    class TrialAccess:
        async def claim_free_trial(self, *_: object, **__: object) -> SimpleNamespace:
            return SimpleNamespace(
                starts_at=started_at,
                ends_at=started_at + timedelta(days=7),
            )

    class StripeMustNotRun:
        async def create_checkout(self, *_: object, **__: object) -> None:
            raise AssertionError("Free Trial must not use Stripe")

    role_syncs: list[tuple[int, bool]] = []

    async def sync_role(user_id: int, enabled: bool) -> None:
        role_syncs.append((user_id, enabled))

    controller = object.__new__(GeneralControlCog)
    controller.guild_id = 123
    controller.free_trial_calendar_days = 7
    controller.access_service = TrialAccess()
    controller.stripe_service = StripeMustNotRun()
    controller.sync_role = sync_role
    interaction = FakeInteraction()
    await controller.activate_plan(interaction, "FREE_TRIAL")

    assert interaction.response.deferred is True
    assert role_syncs == [(456, True)]
    assert "7 个自然日" in interaction.followup.payload["args"][0]


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
