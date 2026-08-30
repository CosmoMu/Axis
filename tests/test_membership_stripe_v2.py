from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    GuildConfig,
    MembershipEntitlement,
    MembershipPrice,
    PaymentEvent,
)
from app.db.session import Database
from app.domain.enums import EntitlementStatus, MembershipExtensionType, MembershipPlanType
from app.domain.public_identity import PublicIdentityPolicy
from app.integrations.stripe_gateway import StripeCheckout, StripeSdkGateway
from app.services.membership_access import (
    MembershipAccessService,
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
)
from app.services.membership_stripe import MembershipStripeError, MembershipStripeService
from app.services.trading_calendar import TradingCalendarService

GUILD_ID = 1543309921066684567
USER_ID = 100000000000000001


class FakeStripeGateway:
    def __init__(self) -> None:
        self.checkout_calls: list[dict[str, Any]] = []
        self.portal_customers: list[str] = []
        self.period_end_cancellations: list[str] = []
        self.immediate_cancellations: list[str] = []

    async def create_checkout(self, **kwargs: Any) -> StripeCheckout:
        self.checkout_calls.append(kwargs)
        index = len(self.checkout_calls)
        return StripeCheckout(f"cs_test_{index}", f"https://checkout.stripe.test/{index}")

    async def create_portal(self, *, customer_id: str) -> str:
        self.portal_customers.append(customer_id)
        return "https://billing.stripe.test/session"

    async def cancel_at_period_end(self, *, subscription_id: str) -> None:
        self.period_end_cancellations.append(subscription_id)

    async def cancel_subscription(self, *, subscription_id: str) -> None:
        self.immediate_cancellations.append(subscription_id)

    def construct_event(self, body: bytes, signature: str | None) -> dict[str, Any]:
        return json.loads(body)


async def setup() -> tuple[
    Database,
    FakeStripeGateway,
    MembershipAccessService,
    MembershipStripeService,
]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        session.add_all(
            [
                MembershipPrice(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000101"),
                    plan_type=MembershipPlanType.DAY_PASS.value,
                    pricing_version="DAY_PASS_V1",
                    stripe_product_id="prod_day",
                    stripe_price_id="price_day_v1",
                    unit_amount=999,
                    currency="usd",
                    billing_interval=None,
                    is_current=True,
                    is_active=True,
                ),
                MembershipPrice(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000102"),
                    plan_type=MembershipPlanType.MONTHLY.value,
                    pricing_version="MONTHLY_V1",
                    stripe_product_id="prod_monthly",
                    stripe_price_id="price_monthly_v1",
                    unit_amount=9999,
                    currency="usd",
                    billing_interval="month",
                    is_current=True,
                    is_active=True,
                ),
            ]
        )
        await session.commit()
    gateway = FakeStripeGateway()
    acknowledgements = MembershipAcknowledgementService(database)
    calendar = TradingCalendarService()
    access = MembershipAccessService(database, calendar, acknowledgements)
    service = MembershipStripeService(
        database,
        gateway,
        calendar,
        acknowledgements,
        MembershipPriceCatalog(database),
    )
    await acknowledgements.accept_risk(GUILD_ID, USER_ID, interaction_id=1)
    return database, gateway, access, service


def checkout_event(
    event_id: str,
    call: dict[str, Any],
    checkout_id: str,
    *,
    plan_type: str,
    subscription_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": checkout_id,
                "object": "checkout.session",
                "client_reference_id": call["membership_session_id"],
                "payment_status": "paid",
                "customer": "cus_axis_test",
                "subscription": subscription_id,
                "metadata": {
                    "discord_user_id": str(call["discord_user_id"]),
                    "membership_type": plan_type,
                    "pricing_version": call["pricing_version"],
                    "membership_session_id": call["membership_session_id"],
                },
            }
        },
    }


@pytest.mark.asyncio
async def test_day_pass_checkout_duplicate_click_webhook_and_idempotency() -> None:
    database, gateway, access, stripe_service = await setup()
    try:
        checkout = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.DAY_PASS.value
        )
        duplicate_click = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.DAY_PASS.value
        )
        assert duplicate_click == checkout
        assert len(gateway.checkout_calls) == 1

        event = checkout_event(
            "evt_day_pass",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.DAY_PASS.value,
        )
        applied = await stripe_service.process_webhook(GUILD_ID, event, actor_user_id=999)
        duplicate = await stripe_service.process_webhook(GUILD_ID, event, actor_user_id=999)
        assert applied.should_have_role is True
        assert duplicate.duplicate is True
        assert await access.count_active(GUILD_ID, USER_ID) == 1
        async with database.session() as session:
            event_count = await session.scalar(select(func.count()).select_from(PaymentEvent))
            entitlement = await session.scalar(select(MembershipEntitlement))
        assert event_count == 1
        assert entitlement is not None
        assert entitlement.pricing_version == "DAY_PASS_V1"
        assert entitlement.unit_amount_at_signup == 999
        assert entitlement.first_trading_day is not None
        assert entitlement.last_trading_day == entitlement.first_trading_day
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_monthly_payment_failure_portal_and_manual_extension_preserve_access() -> None:
    database, gateway, access, stripe_service = await setup()
    now = int(time.time())
    try:
        checkout = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.MONTHLY.value
        )
        assert gateway.checkout_calls[0]["monthly"] is True
        complete = checkout_event(
            "evt_monthly_checkout",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.MONTHLY.value,
            subscription_id="sub_axis_test",
        )
        await stripe_service.process_webhook(GUILD_ID, complete, actor_user_id=999)
        with pytest.raises(MembershipStripeError, match="MONTHLY_ALREADY_ACTIVE"):
            await stripe_service.create_checkout(
                GUILD_ID, USER_ID, MembershipPlanType.MONTHLY.value
            )
        portal = await stripe_service.create_customer_portal(GUILD_ID, USER_ID)
        assert portal.startswith("https://billing.stripe.test")
        assert gateway.portal_customers == ["cus_axis_test"]
        assert await stripe_service.manager_cancel_monthly(GUILD_ID, USER_ID, immediately=False)
        assert gateway.period_end_cancellations == ["sub_axis_test"]
        assert await stripe_service.manager_cancel_monthly(GUILD_ID, USER_ID, immediately=True)
        assert gateway.immediate_cancellations == ["sub_axis_test"]

        paid = {
            "id": "evt_invoice_paid",
            "type": "invoice.paid",
            "created": now,
            "data": {
                "object": {
                    "id": "in_test",
                    "object": "invoice",
                    "subscription": "sub_axis_test",
                    "customer": "cus_axis_test",
                    "lines": {"data": [{"period": {"end": now + 2_592_000}}]},
                }
            },
        }
        await stripe_service.process_webhook(GUILD_ID, paid, actor_user_id=999)
        cancel_at_end = {
            "id": "evt_subscription_cancel_at_end",
            "type": "customer.subscription.updated",
            "created": now + 30,
            "data": {
                "object": {
                    "id": "sub_axis_test",
                    "object": "subscription",
                    "customer": "cus_axis_test",
                    "status": "active",
                    "cancel_at_period_end": True,
                    "current_period_end": now + 2_592_000,
                }
            },
        }
        cancelling = await stripe_service.process_webhook(
            GUILD_ID, cancel_at_end, actor_user_id=999
        )
        assert cancelling.membership_status == EntitlementStatus.CANCEL_AT_PERIOD_END.value
        assert cancelling.should_have_role is True
        failed = {
            "id": "evt_invoice_failed",
            "type": "invoice.payment_failed",
            "created": now + 60,
            "data": {
                "object": {
                    "id": "in_failed",
                    "object": "invoice",
                    "subscription": "sub_axis_test",
                }
            },
        }
        failure = await stripe_service.process_webhook(GUILD_ID, failed, actor_user_id=999)
        assert failure.membership_status == EntitlementStatus.PAST_DUE.value
        assert failure.should_have_role is True

        await access.extend(
            GUILD_ID,
            USER_ID,
            extension_type=MembershipExtensionType.TRADING_DAYS.value,
            amount=5,
            actor_user_id=99,
            interaction_id=10,
        )
        deleted = {
            "id": "evt_subscription_deleted",
            "type": "customer.subscription.deleted",
            "created": now + 120,
            "data": {
                "object": {
                    "id": "sub_axis_test",
                    "object": "subscription",
                    "customer": "cus_axis_test",
                    "status": "canceled",
                }
            },
        }
        cancelled = await stripe_service.process_webhook(GUILD_ID, deleted, actor_user_id=999)
        assert cancelled.membership_status == EntitlementStatus.CANCELLED.value
        assert cancelled.should_have_role is True
        assert await access.count_active(GUILD_ID, USER_ID) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_price_grandfathering_keeps_signup_snapshot() -> None:
    database, gateway, _, stripe_service = await setup()
    try:
        checkout = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.MONTHLY.value
        )
        complete = checkout_event(
            "evt_grandfather",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.MONTHLY.value,
            subscription_id="sub_grandfather",
        )
        await stripe_service.process_webhook(GUILD_ID, complete, actor_user_id=999)
        async with database.session() as session:
            old = await session.scalar(
                select(MembershipPrice).where(MembershipPrice.pricing_version == "MONTHLY_V1")
            )
            assert old is not None
            old.is_current = False
            session.add(
                MembershipPrice(
                    plan_type=MembershipPlanType.MONTHLY.value,
                    pricing_version="MONTHLY_V2",
                    stripe_product_id="prod_monthly",
                    stripe_price_id="price_monthly_v2",
                    unit_amount=12999,
                    currency="usd",
                    billing_interval="month",
                    is_current=True,
                    is_active=True,
                )
            )
            await session.commit()
        async with database.session() as session:
            entitlement = await session.scalar(select(MembershipEntitlement))
        assert entitlement is not None
        assert entitlement.pricing_version == "MONTHLY_V1"
        assert entitlement.stripe_price_id == "price_monthly_v1"
        assert entitlement.unit_amount_at_signup == 9999
    finally:
        await database.dispose()


def test_stripe_signature_and_checkout_metadata_privacy_contract() -> None:
    secret = "whsec_test_only"
    body = b'{"id":"evt_test","type":"invoice.paid","data":{"object":{}}}'
    timestamp = int(time.time())
    digest = hmac.new(
        secret.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    gateway = StripeSdkGateway(
        secret_key="sk_test_placeholder",
        webhook_secret=secret,
        success_url="https://axis.example/success",
        cancel_url="https://axis.example/cancel",
        portal_return_url="https://axis.example/account",
    )
    event = gateway.construct_event(body, f"t={timestamp},v1={digest}")
    assert event["id"] == "evt_test"

    policy = PublicIdentityPolicy(owner_user_id=999999999999999999)
    public_payment_copy = {
        "product": "AXIS Membership",
        "description": "Market analysis, trading alerts, trade tracking and community access.",
    }
    policy.assert_public(public_payment_copy)
