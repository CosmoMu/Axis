from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.bot.cogs.manager_control import ManagerControlCog, _payment_notice
from app.db.base import Base
from app.db.models import GuildConfig
from app.db.session import Database
from app.services.membership_stripe import StripeWebhookApplication

GUILD_ID = 1543309921066684567
USER_ID = 900000000000000001


def _result(*, duplicate: bool = False) -> StripeWebhookApplication:
    return StripeWebhookApplication(duplicate, USER_ID, "ACTIVE", True)


def _checkout_event(plan: str = "MONTHLY") -> dict[str, object]:
    return {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "payment_status": "paid",
                "amount_total": 14999,
                "currency": "usd",
                "metadata": {"membership_type": plan},
            }
        },
    }


def test_payment_notice_deduplicates_initial_subscription_invoice() -> None:
    assert _payment_notice(_checkout_event(), _result()) == (
        USER_ID,
        "月度会员",
        "首次购买",
        "$149.99 USD",
    )
    initial_invoice = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "billing_reason": "subscription_create",
                "amount_paid": 14999,
                "currency": "usd",
            }
        },
    }
    assert _payment_notice(initial_invoice, _result()) is None
    assert _payment_notice(_checkout_event(), _result(duplicate=True)) is None


def test_payment_notice_includes_monthly_renewal() -> None:
    renewal = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "billing_reason": "subscription_cycle",
                "amount_paid": 14999,
                "currency": "usd",
            }
        },
    }
    assert _payment_notice(renewal, _result()) == (
        USER_ID,
        "月度会员",
        "自动续费",
        "$149.99 USD",
    )


class _PaymentChannel:
    def __init__(self) -> None:
        self.sent: list[dict[str, object]] = []

    async def send(self, **kwargs: object) -> SimpleNamespace:
        self.sent.append(kwargs)
        return SimpleNamespace(id=20)


@pytest.mark.asyncio
async def test_successful_payment_notifies_managers_then_repins_control() -> None:
    channel = _PaymentChannel()
    controller = object.__new__(ManagerControlCog)
    controller.bot = SimpleNamespace(
        get_channel=lambda channel_id: channel if channel_id == 77 else None,
    )
    controller.member_channel_id = 77
    controller._member_panel_lock = asyncio.Lock()
    repins: list[bool] = []

    async def ensure_member_panel(*, force_repost: bool = False) -> None:
        repins.append(force_repost)

    controller._ensure_member_panel = ensure_member_panel

    await controller.notify_successful_payment(_checkout_event(), _result())

    assert len(channel.sent) == 1
    embed = channel.sent[0]["embed"]
    assert embed.title == "💳 会员付款成功"
    assert f"<@{USER_ID}>" in embed.description
    assert any(field.name == "金额" and field.value == "$149.99 USD" for field in embed.fields)
    assert repins == [True]


class _PanelMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id
        self.deleted = False

    async def edit(self, **_kwargs: object) -> None:
        return None

    async def delete(self) -> None:
        self.deleted = True


class _PanelChannel:
    def __init__(self, old: _PanelMessage) -> None:
        self.old = old
        self.new = _PanelMessage(11)

    async def fetch_message(self, message_id: int) -> _PanelMessage:
        assert message_id == self.old.id
        return self.old

    async def send(self, **_kwargs: object) -> _PanelMessage:
        return self.new

    def history(self, *, limit: int):
        async def generate():
            if limit:
                yield self.old

        return generate()


@pytest.mark.asyncio
async def test_force_repost_replaces_saved_member_control_panel() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID, member_panel_message_id=10))
        await session.commit()

    old = _PanelMessage(10)
    channel = _PanelChannel(old)
    controller = object.__new__(ManagerControlCog)
    controller.bot = SimpleNamespace(
        user=SimpleNamespace(id=42),
        get_channel=lambda channel_id: channel if channel_id == 77 else None,
    )
    controller.guild_id = GUILD_ID
    controller.member_channel_id = 77
    controller.membership_service = SimpleNamespace(database=database)

    try:
        await controller._ensure_member_panel(force_repost=True)
        assert old.deleted is True
        async with database.session() as session:
            config = await session.get(GuildConfig, GUILD_ID)
        assert config is not None
        assert config.member_panel_message_id == 11
    finally:
        await database.dispose()
