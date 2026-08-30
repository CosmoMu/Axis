from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Membership,
    MembershipSession,
    PaymentWebhookEvent,
    Subscription,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import MembershipSource, MembershipStatus
from app.integrations.payment_provider import (
    CheckoutMetadata,
    PaymentEvent,
    PaymentProvider,
)
from app.services.membership_management import MembershipManagementService


class MembershipPaymentError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CheckoutSession:
    session_id: str
    discord_user_id: int
    expires_at: datetime
    checkout_url: str


@dataclass(frozen=True, slots=True)
class PaymentApplication:
    duplicate: bool
    discord_user_id: int
    membership_status: str
    should_have_role: bool


ACTIVE_PAYMENT_STATUSES = {
    MembershipStatus.ACTIVE.value,
    MembershipStatus.CANCEL_AT_PERIOD_END.value,
}


class MembershipPaymentService:
    def __init__(
        self,
        database: Database,
        provider: PaymentProvider,
        *,
        subscription_url: str | None,
        session_ttl_minutes: int,
    ) -> None:
        self.database = database
        self.provider = provider
        self.subscription_url = subscription_url
        self.session_ttl_minutes = session_ttl_minutes

    async def create_checkout_session(self, guild_id: int, discord_user_id: int) -> CheckoutSession:
        if self.subscription_url is None:
            raise MembershipPaymentError("SUBSCRIPTION_URL_NOT_CONFIGURED")
        if discord_user_id <= 0:
            raise MembershipPaymentError("DISCORD_USER_ID_INVALID")
        now = utc_now()
        expires_at = now + timedelta(minutes=self.session_ttl_minutes)
        session_id = secrets.token_urlsafe(32)
        metadata = CheckoutMetadata(
            session_id=session_id,
            discord_user_id=discord_user_id,
            provider=self.provider.name,
        )
        checkout_url = self.provider.checkout_url(self.subscription_url, metadata)
        async with self.database.session() as session:
            session.add(
                MembershipSession(
                    session_id=session_id,
                    guild_id=guild_id,
                    discord_user_id=discord_user_id,
                    provider=self.provider.name,
                    created_at=now,
                    expires_at=expires_at,
                )
            )
            await session.commit()
        return CheckoutSession(session_id, discord_user_id, expires_at, checkout_url)

    async def apply_event(
        self,
        guild_id: int,
        event: PaymentEvent,
        *,
        actor_user_id: int,
        payload_bytes: bytes,
    ) -> PaymentApplication:
        if event.provider != self.provider.name:
            raise MembershipPaymentError("PAYMENT_PROVIDER_MISMATCH")
        target_status = (
            MembershipStatus.CANCEL_AT_PERIOD_END.value
            if event.status == MembershipStatus.ACTIVE.value and event.cancel_at_period_end
            else event.status
        )
        if target_status in ACTIVE_PAYMENT_STATUSES and event.current_period_end is None:
            raise MembershipPaymentError("PAYMENT_PERIOD_END_REQUIRED")
        now = utc_now()
        payload_hash = hashlib.sha256(payload_bytes).hexdigest()
        async with self.database.session() as session:
            previous = await session.scalar(
                select(PaymentWebhookEvent).where(
                    PaymentWebhookEvent.provider == event.provider,
                    PaymentWebhookEvent.provider_event_id == event.provider_event_id,
                )
            )
            if previous is not None:
                return await self._duplicate_application(
                    session,
                    guild_id,
                    event,
                    previous,
                )

            webhook = PaymentWebhookEvent(
                provider=event.provider,
                provider_event_id=event.provider_event_id,
                event_type=event.event_type,
                # Link only after identity validation. This prevents an invalid
                # session FK from being mistaken for a duplicate event conflict.
                membership_session_id=None,
                payload_hash=payload_hash,
                status="PROCESSING",
            )
            session.add(webhook)
            try:
                await session.flush()
            except IntegrityError as exc:
                await session.rollback()
                concurrent = await session.scalar(
                    select(PaymentWebhookEvent).where(
                        PaymentWebhookEvent.provider == event.provider,
                        PaymentWebhookEvent.provider_event_id == event.provider_event_id,
                    )
                )
                if concurrent is None:
                    raise MembershipPaymentError("PAYMENT_EVENT_CONFLICT") from exc
                return await self._duplicate_application(
                    session,
                    guild_id,
                    event,
                    concurrent,
                )

            try:
                user_id, membership_session = await self._resolve_identity(
                    session, guild_id, event, now
                )
                if membership_session is not None:
                    webhook.membership_session_id = membership_session.session_id
                membership = await session.scalar(
                    select(Membership)
                    .where(
                        Membership.guild_id == guild_id,
                        Membership.user_id == user_id,
                    )
                    .with_for_update()
                )
                before = (
                    MembershipManagementService._payload(membership)
                    if membership is not None
                    else None
                )
                if membership is None:
                    membership = Membership(
                        guild_id=guild_id,
                        user_id=user_id,
                        status=target_status,
                        source=MembershipSource.PAYMENT.value,
                        provider=event.provider,
                        provider_customer_id=event.provider_customer_id,
                        provider_subscription_id=event.provider_subscription_id,
                        starts_at=event.current_period_start or now,
                        ends_at=event.current_period_end,
                        cancel_at_period_end=event.cancel_at_period_end,
                        created_by=actor_user_id,
                    )
                    session.add(membership)
                else:
                    membership.status = target_status
                    membership.source = MembershipSource.PAYMENT.value
                    membership.provider = event.provider
                    membership.provider_customer_id = event.provider_customer_id
                    membership.provider_subscription_id = event.provider_subscription_id
                    membership.starts_at = event.current_period_start or membership.starts_at
                    membership.ends_at = event.current_period_end or membership.ends_at
                    membership.cancel_at_period_end = (
                        event.cancel_at_period_end
                        or event.status == MembershipStatus.CANCEL_AT_PERIOD_END.value
                    )
                    membership.removal_reason = (
                        "payment_inactive" if event.status not in ACTIVE_PAYMENT_STATUSES else None
                    )
                    membership.version += 1
                if membership.status in {
                    MembershipStatus.CANCELLED.value,
                    MembershipStatus.EXPIRED.value,
                }:
                    membership.ends_at = now
                    membership.cancel_at_period_end = False
                await session.flush()
                subscription = await session.scalar(
                    select(Subscription)
                    .where(
                        Subscription.provider == event.provider,
                        Subscription.external_subscription_id == event.provider_subscription_id,
                    )
                    .with_for_update()
                )
                if subscription is None:
                    subscription = Subscription(
                        guild_id=guild_id,
                        user_id=user_id,
                        provider=event.provider,
                        external_customer_id=event.provider_customer_id,
                        external_subscription_id=event.provider_subscription_id,
                        status=event.status,
                        current_period_start=event.current_period_start,
                        current_period_end=event.current_period_end,
                        cancel_at_period_end=membership.cancel_at_period_end,
                    )
                    session.add(subscription)
                else:
                    subscription.user_id = user_id
                    subscription.external_customer_id = event.provider_customer_id
                    subscription.status = event.status
                    subscription.current_period_start = event.current_period_start
                    subscription.current_period_end = event.current_period_end
                    subscription.cancel_at_period_end = membership.cancel_at_period_end
                if membership_session is not None and membership_session.used_at is None:
                    membership_session.used_at = now
                action = {
                    MembershipStatus.ACTIVE.value: "PAYMENT_MEMBERSHIP_ACTIVATED",
                    MembershipStatus.CANCEL_AT_PERIOD_END.value: (
                        "PAYMENT_MEMBERSHIP_CANCEL_AT_PERIOD_END"
                    ),
                    MembershipStatus.PAST_DUE.value: "PAYMENT_MEMBERSHIP_PAST_DUE",
                    MembershipStatus.CANCELLED.value: "PAYMENT_MEMBERSHIP_CANCELLED",
                    MembershipStatus.EXPIRED.value: "PAYMENT_MEMBERSHIP_EXPIRED",
                }[membership.status]
                await MembershipManagementService._record_change(
                    session,
                    membership,
                    action=action,
                    actor_user_id=actor_user_id,
                    interaction_id=None,
                    before=before,
                    reason=f"payment_webhook:{event.event_type}",
                )
                if membership.status in ACTIVE_PAYMENT_STATUSES:
                    await MembershipManagementService._reschedule(session, membership)
                else:
                    await MembershipManagementService._cancel_jobs(session, membership.id)
                webhook.status = "PROCESSED"
                webhook.processed_at = now
                await session.commit()
                return PaymentApplication(
                    False,
                    user_id,
                    membership.status,
                    membership.status in ACTIVE_PAYMENT_STATUSES,
                )
            except MembershipPaymentError as exc:
                webhook.status = "FAILED"
                webhook.error_type = exc.code
                webhook.processed_at = now
                await session.commit()
                raise

    async def _duplicate_application(
        self,
        session: AsyncSession,
        guild_id: int,
        event: PaymentEvent,
        webhook: PaymentWebhookEvent,
    ) -> PaymentApplication:
        if webhook.status == "FAILED":
            raise MembershipPaymentError(
                webhook.error_type or "PAYMENT_EVENT_PREVIOUSLY_FAILED"
            )
        user_id = await self._resolve_existing_user(session, event)
        membership = await session.scalar(
            select(Membership).where(
                Membership.guild_id == guild_id,
                Membership.user_id == user_id,
            )
        )
        status = membership.status if membership else MembershipStatus.CANCELLED.value
        return PaymentApplication(
            True,
            user_id,
            status,
            status in ACTIVE_PAYMENT_STATUSES,
        )

    async def _resolve_existing_user(self, session: AsyncSession, event: PaymentEvent) -> int:
        if event.provider_subscription_id:
            subscription = await session.scalar(
                select(Subscription).where(
                    Subscription.provider == event.provider,
                    Subscription.external_subscription_id == event.provider_subscription_id,
                )
            )
            if subscription is not None:
                return subscription.user_id
        if event.discord_user_id:
            return event.discord_user_id
        raise MembershipPaymentError("PAYMENT_IDENTITY_NOT_FOUND")

    async def _resolve_identity(
        self,
        session: AsyncSession,
        guild_id: int,
        event: PaymentEvent,
        now: datetime,
    ) -> tuple[int, MembershipSession | None]:
        if event.provider_subscription_id:
            subscription = await session.scalar(
                select(Subscription).where(
                    Subscription.provider == event.provider,
                    Subscription.external_subscription_id == event.provider_subscription_id,
                )
            )
            if subscription is not None:
                if event.discord_user_id and event.discord_user_id != subscription.user_id:
                    raise MembershipPaymentError("PAYMENT_IDENTITY_MISMATCH")
                return subscription.user_id, None
        if not event.membership_session_id or not event.discord_user_id:
            raise MembershipPaymentError("PAYMENT_SESSION_METADATA_REQUIRED")
        membership_session = await session.scalar(
            select(MembershipSession)
            .where(MembershipSession.session_id == event.membership_session_id)
            .with_for_update()
        )
        if (
            membership_session is None
            or membership_session.guild_id != guild_id
            or membership_session.provider != event.provider
        ):
            raise MembershipPaymentError("PAYMENT_SESSION_NOT_FOUND")
        if membership_session.discord_user_id != event.discord_user_id:
            raise MembershipPaymentError("PAYMENT_IDENTITY_MISMATCH")
        if membership_session.used_at is not None:
            raise MembershipPaymentError("PAYMENT_SESSION_ALREADY_USED")
        expires_at = membership_session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= now and membership_session.used_at is None:
            raise MembershipPaymentError("PAYMENT_SESSION_EXPIRED")
        return membership_session.discord_user_id, membership_session
