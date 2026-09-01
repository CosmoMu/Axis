from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    GuildConfig,
    Membership,
    MembershipEvent,
    MembershipSession,
    NewcomerProfile,
    PaymentWebhookEvent,
    Subscription,
)
from app.db.session import Database
from app.domain.enums import MembershipStatus
from app.integrations.payment_provider import (
    CheckoutMetadata,
    ExternalCheckoutProvider,
)
from app.services.membership_payments import (
    MembershipPaymentError,
    MembershipPaymentService,
)

GUILD_ID = 1543309921066684567
USER_ID = 100000000000000001


def approved_profile() -> NewcomerProfile:
    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    return NewcomerProfile(
        guild_id=GUILD_ID,
        discord_user_id=USER_ID,
        discord_username_snapshot="approved_user",
        discord_display_name_snapshot="Approved User",
        first_joined_at=now,
        last_joined_at=now,
        join_count=1,
        approved_at=now,
    )


def event_payload(
    event_id: str,
    *,
    status: str,
    session_id: str | None,
    user_id: int | None,
    subscription_id: str = "sub_axis_1",
    cancel_at_period_end: bool = False,
) -> dict[str, object]:
    now = datetime.now(UTC)
    metadata = {}
    if session_id:
        metadata["membership_session_id"] = session_id
    if user_id:
        metadata["discord_user_id"] = str(user_id)
    return {
        "event_id": event_id,
        "event_type": {
            "ACTIVE": "subscription.active",
            "CANCEL_AT_PERIOD_END": "subscription.updated",
            "CANCELLED": "subscription.cancelled",
        }[status],
        "status": status,
        "metadata": metadata,
        "customer_id": "cus_axis_1",
        "subscription_id": subscription_id,
        "current_period_start": now.isoformat(),
        "current_period_end": (now + timedelta(days=30)).isoformat(),
        "cancel_at_period_end": cancel_at_period_end,
    }


def test_external_provider_preserves_discord_metadata_and_verifies_hmac() -> None:
    provider = ExternalCheckoutProvider()
    url = provider.checkout_url(
        "https://pay.example/axis?campaign=discord",
        CheckoutMetadata("session-1", USER_ID, provider.name),
    )
    query = parse_qs(urlsplit(url).query)

    assert query["campaign"] == ["discord"]
    assert query["discord_user_id"] == [str(USER_ID)]
    assert query["membership_session_id"] == ["session-1"]
    body = b'{"event_id":"evt_1"}'
    secret = "test-secret"
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert provider.verify_signature(body, f"sha256={signature}", secret)
    assert not provider.verify_signature(body + b"x", signature, secret)


@pytest.mark.asyncio
async def test_legacy_checkout_session_backend_also_requires_approval() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()
        service = MembershipPaymentService(
            database,
            ExternalCheckoutProvider(),
            subscription_url="https://pay.example/axis",
            session_ttl_minutes=30,
        )
        with pytest.raises(MembershipPaymentError, match="ACCESS_APPROVAL_REQUIRED"):
            await service.create_checkout_session(GUILD_ID, USER_ID)
        async with database.session() as session:
            profile = approved_profile()
            profile.role_sync_status = "FAILED"
            session.add(profile)
            await session.commit()
        with pytest.raises(MembershipPaymentError, match="ACCESS_APPROVAL_REQUIRED"):
            await service.create_checkout_session(GUILD_ID, USER_ID)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_payment_activation_cancel_and_idempotency_drive_membership_role_state() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    provider = ExternalCheckoutProvider()
    service = MembershipPaymentService(
        database,
        provider,
        subscription_url="https://pay.example/axis",
        session_ttl_minutes=30,
    )
    try:
        async with database.session() as session:
            session.add_all([GuildConfig(guild_id=GUILD_ID), approved_profile()])
            await session.commit()

        checkout = await service.create_checkout_session(GUILD_ID, USER_ID)
        active_payload = event_payload(
            "evt_active",
            status="ACTIVE",
            session_id=checkout.session_id,
            user_id=USER_ID,
        )
        active_body = json.dumps(active_payload, sort_keys=True).encode()
        active = await service.apply_event(
            GUILD_ID,
            provider.parse_event(active_payload),
            actor_user_id=999,
            payload_bytes=active_body,
        )
        duplicate = await service.apply_event(
            GUILD_ID,
            provider.parse_event(active_payload),
            actor_user_id=999,
            payload_bytes=active_body,
        )
        assert active.should_have_role is True
        assert duplicate.duplicate is True

        cancel_payload = event_payload(
            "evt_cancel_period",
            status="CANCEL_AT_PERIOD_END",
            session_id=None,
            user_id=None,
            cancel_at_period_end=True,
        )
        cancel = await service.apply_event(
            GUILD_ID,
            provider.parse_event(cancel_payload),
            actor_user_id=999,
            payload_bytes=json.dumps(cancel_payload, sort_keys=True).encode(),
        )
        assert cancel.membership_status == MembershipStatus.CANCEL_AT_PERIOD_END.value
        assert cancel.should_have_role is True

        revoked_payload = event_payload(
            "evt_cancelled",
            status="CANCELLED",
            session_id=None,
            user_id=None,
        )
        revoked = await service.apply_event(
            GUILD_ID,
            provider.parse_event(revoked_payload),
            actor_user_id=999,
            payload_bytes=json.dumps(revoked_payload, sort_keys=True).encode(),
        )
        assert revoked.membership_status == MembershipStatus.CANCELLED.value
        assert revoked.should_have_role is False

        async with database.session() as session:
            membership = await session.scalar(select(Membership))
            subscription = await session.scalar(select(Subscription))
            stored_session = await session.get(MembershipSession, checkout.session_id)
            webhook_count = await session.scalar(
                select(func.count()).select_from(PaymentWebhookEvent)
            )
            event_count = await session.scalar(select(func.count()).select_from(MembershipEvent))
        assert membership is not None
        assert membership.user_id == USER_ID
        assert membership.provider == "external"
        assert membership.provider_customer_id == "cus_axis_1"
        assert membership.provider_subscription_id == "sub_axis_1"
        assert subscription is not None and subscription.user_id == USER_ID
        assert stored_session is not None and stored_session.used_at is not None
        assert webhook_count == event_count == 3
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_payment_metadata_mismatch_is_rejected_without_membership() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    provider = ExternalCheckoutProvider()
    service = MembershipPaymentService(
        database,
        provider,
        subscription_url="https://pay.example/axis",
        session_ttl_minutes=30,
    )
    try:
        async with database.session() as session:
            session.add_all([GuildConfig(guild_id=GUILD_ID), approved_profile()])
            await session.commit()
        checkout = await service.create_checkout_session(GUILD_ID, USER_ID)
        payload = event_payload(
            "evt_mismatch",
            status="ACTIVE",
            session_id=checkout.session_id,
            user_id=USER_ID + 1,
            subscription_id="sub_axis_bad",
        )
        with pytest.raises(MembershipPaymentError, match="PAYMENT_IDENTITY_MISMATCH"):
            await service.apply_event(
                GUILD_ID,
                provider.parse_event(payload),
                actor_user_id=999,
                payload_bytes=json.dumps(payload).encode(),
            )
        async with database.session() as session:
            membership_count = await session.scalar(select(func.count()).select_from(Membership))
            failed = await session.scalar(select(PaymentWebhookEvent))
        assert membership_count == 0
        assert failed is not None and failed.status == "FAILED"
        assert failed.error_type == "PAYMENT_IDENTITY_MISMATCH"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_unknown_membership_session_never_grants_membership() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    provider = ExternalCheckoutProvider()
    service = MembershipPaymentService(
        database,
        provider,
        subscription_url="https://pay.example/axis",
        session_ttl_minutes=30,
    )
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()
        payload = event_payload(
            "evt_unknown_session",
            status="ACTIVE",
            session_id="session-does-not-exist",
            user_id=USER_ID,
            subscription_id="sub_axis_unknown",
        )

        with pytest.raises(MembershipPaymentError, match="PAYMENT_SESSION_NOT_FOUND"):
            await service.apply_event(
                GUILD_ID,
                provider.parse_event(payload),
                actor_user_id=999,
                payload_bytes=json.dumps(payload).encode(),
            )

        async with database.session() as session:
            membership_count = await session.scalar(select(func.count()).select_from(Membership))
            failed = await session.scalar(select(PaymentWebhookEvent))
        assert membership_count == 0
        assert failed is not None
        assert failed.status == "FAILED"
        assert failed.error_type == "PAYMENT_SESSION_NOT_FOUND"
        assert failed.membership_session_id is None
    finally:
        await database.dispose()
