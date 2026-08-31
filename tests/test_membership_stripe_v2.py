from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
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
from app.integrations.stripe_config import StripeMode
from app.integrations.stripe_gateway import (
    StripeCheckout,
    StripeSdkGateway,
    StripeSubscriptionSnapshot,
)
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
        self.subscriptions: tuple[StripeSubscriptionSnapshot, ...] = ()

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

    async def list_subscriptions(self) -> tuple[StripeSubscriptionSnapshot, ...]:
        return self.subscriptions

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
        "livemode": False,
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
                    "environment": "TEST",
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
        assert entitlement.payment_environment == "TEST"
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
            "livemode": False,
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
            "livemode": False,
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
        final_period_paid = {
            **paid,
            "id": "evt_final_period_invoice_paid",
            "created": now + 45,
        }
        still_cancelling = await stripe_service.process_webhook(
            GUILD_ID, final_period_paid, actor_user_id=999
        )
        assert still_cancelling.membership_status == EntitlementStatus.CANCEL_AT_PERIOD_END.value
        assert still_cancelling.should_have_role is True
        failed = {
            "id": "evt_invoice_failed",
            "livemode": False,
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
            "livemode": False,
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
async def test_monthly_invoice_before_checkout_is_safe_to_replay() -> None:
    database, gateway, access, stripe_service = await setup()
    now = int(time.time())
    try:
        checkout = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.MONTHLY.value
        )
        invoice = {
            "id": "evt_invoice_before_checkout",
            "livemode": False,
            "type": "invoice.paid",
            "created": now,
            "data": {
                "object": {
                    "id": "in_before_checkout",
                    "object": "invoice",
                    "subscription": "sub_out_of_order",
                    "customer": "cus_axis_test",
                    "lines": {"data": [{"period": {"end": now + 2_592_000}}]},
                }
            },
        }
        with pytest.raises(MembershipStripeError, match="STRIPE_SUBSCRIPTION_NOT_LINKED"):
            await stripe_service.process_webhook(GUILD_ID, invoice, actor_user_id=999)

        complete = checkout_event(
            "evt_checkout_after_invoice",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.MONTHLY.value,
            subscription_id="sub_out_of_order",
        )
        checkout_result = await stripe_service.process_webhook(
            GUILD_ID, complete, actor_user_id=999
        )
        replayed = await stripe_service.process_webhook(GUILD_ID, invoice, actor_user_id=999)

        assert checkout_result.should_have_role is True
        assert replayed.duplicate is True
        assert replayed.membership_status == EntitlementStatus.ACTIVE.value
        assert await access.count_active(GUILD_ID, USER_ID) == 1
        async with database.session() as session:
            stored = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider_event_id == "evt_invoice_before_checkout"
                )
            )
        assert stored is not None
        assert stored.processing_status == "PROCESSED"
        assert stored.error_type is None
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


@pytest.mark.asyncio
async def test_payments_kill_switch_blocks_checkout_but_not_signed_webhook() -> None:
    database, gateway, access, enabled_service = await setup()
    try:
        checkout = await enabled_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.DAY_PASS.value
        )
        disabled_service = MembershipStripeService(
            database,
            gateway,
            TradingCalendarService(),
            MembershipAcknowledgementService(database),
            MembershipPriceCatalog(database),
            mode=StripeMode.TEST,
            payments_enabled=False,
        )
        with pytest.raises(MembershipStripeError, match="PAYMENTS_DISABLED"):
            await disabled_service.create_checkout(
                GUILD_ID, USER_ID + 1, MembershipPlanType.DAY_PASS.value
            )
        event = checkout_event(
            "evt_kill_switch_webhook",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.DAY_PASS.value,
        )
        result = await disabled_service.process_webhook(GUILD_ID, event, actor_user_id=999)
        assert result.should_have_role is True
        assert await access.count_active(GUILD_ID, USER_ID) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_webhook_livemode_mismatch_is_rejected_before_event_reservation() -> None:
    database, gateway, _, stripe_service = await setup()
    try:
        checkout = await stripe_service.create_checkout(
            GUILD_ID, USER_ID, MembershipPlanType.DAY_PASS.value
        )
        event = checkout_event(
            "evt_wrong_environment",
            gateway.checkout_calls[0],
            checkout.id,
            plan_type=MembershipPlanType.DAY_PASS.value,
        )
        event["livemode"] = True
        with pytest.raises(MembershipStripeError, match="STRIPE_EVENT_ENVIRONMENT_MISMATCH"):
            await stripe_service.process_webhook(GUILD_ID, event, actor_user_id=999)
        async with database.session() as session:
            count = await session.scalar(select(func.count()).select_from(PaymentEvent))
        assert count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_reconciliation_repairs_missing_membership_without_changing_price() -> None:
    database, gateway, access, stripe_service = await setup()
    other_user = USER_ID + 10
    gateway.subscriptions = (
        StripeSubscriptionSnapshot(
            id="sub_recovered",
            customer_id="cus_recovered",
            status="active",
            cancel_at_period_end=False,
            current_period_end=datetime(2026, 9, 30, tzinfo=UTC),
            created_at=datetime(2026, 8, 31, tzinfo=UTC),
            metadata={
                "discord_user_id": str(other_user),
                "membership_type": "MONTHLY",
                "pricing_version": "MONTHLY_V1",
                "environment": "TEST",
            },
            price_id="price_monthly_v1",
        ),
    )
    try:
        dry_run = await stripe_service.reconcile_subscriptions(
            GUILD_ID, actor_user_id=999, apply=False
        )
        assert dry_run.repaired_count == 0
        assert dry_run.items[0].action == "CREATE_MISSING_MEMBERSHIP"
        assert not await access.should_have_access(GUILD_ID, other_user)

        applied = await stripe_service.reconcile_subscriptions(
            GUILD_ID, actor_user_id=999, apply=True
        )
        assert applied.repaired_count == 1
        assert await access.should_have_access(GUILD_ID, other_user)
        async with database.session() as session:
            entitlement = await session.scalar(
                select(MembershipEntitlement).where(
                    MembershipEntitlement.provider_subscription_id == "sub_recovered"
                )
            )
        assert entitlement is not None
        assert entitlement.pricing_version == "MONTHLY_V1"
        assert entitlement.unit_amount_at_signup == 9999
        assert entitlement.payment_environment == "TEST"
    finally:
        await database.dispose()
