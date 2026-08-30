from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (
    AuditLog,
    MembershipEntitlement,
    MembershipPrice,
    MembershipSession,
    PaymentEvent,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import EntitlementStatus, EntitlementType, MembershipPlanType
from app.integrations.stripe_gateway import StripeCheckout, StripeGateway, StripeGatewayError
from app.services.membership_access import (
    ACCESS_STATUSES,
    MembershipAccessError,
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
)
from app.services.trading_calendar import TradingCalendarService

SUPPORTED_STRIPE_EVENTS = {
    "checkout.session.completed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}


class MembershipStripeError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class StripeWebhookApplication:
    duplicate: bool
    discord_user_id: int | None
    membership_status: str | None
    should_have_role: bool | None


class MembershipStripeService:
    def __init__(
        self,
        database: Database,
        gateway: StripeGateway | None,
        calendar: TradingCalendarService,
        acknowledgements: MembershipAcknowledgementService,
        prices: MembershipPriceCatalog,
        *,
        session_ttl_minutes: int = 30,
    ) -> None:
        self.database = database
        self.gateway = gateway
        self.calendar = calendar
        self.acknowledgements = acknowledgements
        self.prices = prices
        self.session_ttl_minutes = session_ttl_minutes

    @property
    def enabled(self) -> bool:
        return self.gateway is not None

    async def create_checkout(
        self,
        guild_id: int,
        user_id: int,
        plan_type: str,
    ) -> StripeCheckout:
        if self.gateway is None:
            raise MembershipStripeError("STRIPE_CHECKOUT_DISABLED")
        if not await self.acknowledgements.has_current_risk(user_id):
            raise MembershipStripeError("RISK_ACKNOWLEDGEMENT_REQUIRED")
        if plan_type not in {MembershipPlanType.DAY_PASS.value, MembershipPlanType.MONTHLY.value}:
            raise MembershipStripeError("MEMBERSHIP_PLAN_INVALID")
        try:
            price = await self.prices.current(plan_type)
        except MembershipAccessError as exc:
            raise MembershipStripeError(exc.code) from exc
        if not price.stripe_price_id:
            raise MembershipStripeError("STRIPE_PRICE_NOT_CONFIGURED")
        now = utc_now()
        async with self.database.session() as session:
            if plan_type == MembershipPlanType.MONTHLY.value:
                existing_monthly = await session.scalar(
                    select(MembershipEntitlement.id).where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.entitlement_type == EntitlementType.MONTHLY.value,
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                        (
                            (MembershipEntitlement.status == EntitlementStatus.PAST_DUE.value)
                            | MembershipEntitlement.ends_at.is_(None)
                            | (MembershipEntitlement.ends_at > now)
                        ),
                    )
                )
                if existing_monthly is not None:
                    raise MembershipStripeError("MONTHLY_ALREADY_ACTIVE")
            reusable = await session.scalar(
                select(MembershipSession)
                .where(
                    MembershipSession.guild_id == guild_id,
                    MembershipSession.discord_user_id == user_id,
                    MembershipSession.provider == "stripe",
                    MembershipSession.membership_type == plan_type,
                    MembershipSession.pricing_version == price.pricing_version,
                    MembershipSession.used_at.is_(None),
                    MembershipSession.expires_at > now,
                    MembershipSession.checkout_url.is_not(None),
                )
                .order_by(MembershipSession.created_at.desc())
            )
            if reusable is not None and reusable.provider_checkout_session_id:
                return StripeCheckout(
                    reusable.provider_checkout_session_id,
                    str(reusable.checkout_url),
                )
            token = secrets.token_urlsafe(32)[:64]
            session.add(
                MembershipSession(
                    session_id=token,
                    guild_id=guild_id,
                    discord_user_id=user_id,
                    provider="stripe",
                    membership_type=plan_type,
                    pricing_version=price.pricing_version,
                    membership_price_id=price.id,
                    expires_at=now + timedelta(minutes=self.session_ttl_minutes),
                )
            )
            await session.commit()
        try:
            checkout = await self.gateway.create_checkout(
                price_id=price.stripe_price_id,
                membership_session_id=token,
                discord_user_id=user_id,
                membership_type=plan_type,
                pricing_version=price.pricing_version,
                monthly=plan_type == MembershipPlanType.MONTHLY.value,
            )
        except StripeGatewayError as exc:
            raise MembershipStripeError(exc.code) from exc
        async with self.database.session() as session:
            membership_session = await session.get(MembershipSession, token)
            if membership_session is None:
                raise MembershipStripeError("MEMBERSHIP_SESSION_NOT_FOUND")
            membership_session.provider_checkout_session_id = checkout.id
            membership_session.checkout_url = checkout.url
            await session.commit()
        return checkout

    async def create_customer_portal(self, guild_id: int, user_id: int) -> str:
        if self.gateway is None:
            raise MembershipStripeError("STRIPE_PORTAL_DISABLED")
        async with self.database.session() as session:
            entitlement = await session.scalar(
                select(MembershipEntitlement)
                .where(
                    MembershipEntitlement.guild_id == guild_id,
                    MembershipEntitlement.discord_user_id == user_id,
                    MembershipEntitlement.entitlement_type == EntitlementType.MONTHLY.value,
                    MembershipEntitlement.provider == "stripe",
                    MembershipEntitlement.provider_customer_id.is_not(None),
                )
                .order_by(MembershipEntitlement.created_at.desc())
            )
            if entitlement is None or not entitlement.provider_customer_id:
                raise MembershipStripeError("STRIPE_CUSTOMER_NOT_FOUND")
            customer_id = entitlement.provider_customer_id
        try:
            return await self.gateway.create_portal(customer_id=customer_id)
        except StripeGatewayError as exc:
            raise MembershipStripeError(exc.code) from exc

    async def manager_cancel_monthly(
        self, guild_id: int, user_id: int, *, immediately: bool
    ) -> bool:
        async with self.database.session() as session:
            entitlements = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.entitlement_type == EntitlementType.MONTHLY.value,
                        MembershipEntitlement.provider == "stripe",
                        MembershipEntitlement.provider_subscription_id.is_not(None),
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                    )
                    .order_by(MembershipEntitlement.created_at.desc())
                )
            ).all()
            subscription_ids = tuple(
                dict.fromkeys(
                    item.provider_subscription_id
                    for item in entitlements
                    if item.provider_subscription_id
                )
            )
            if not subscription_ids:
                return False
        if self.gateway is None:
            raise MembershipStripeError("STRIPE_SUBSCRIPTION_CONTROL_DISABLED")
        try:
            for subscription_id in subscription_ids:
                if immediately:
                    await self.gateway.cancel_subscription(subscription_id=subscription_id)
                else:
                    await self.gateway.cancel_at_period_end(subscription_id=subscription_id)
        except StripeGatewayError as exc:
            raise MembershipStripeError(exc.code) from exc
        return True

    async def process_webhook(
        self,
        guild_id: int,
        event: dict[str, Any],
        *,
        actor_user_id: int,
    ) -> StripeWebhookApplication:
        event_id = str(event.get("id") or "").strip()
        event_type = str(event.get("type") or "").strip()
        if not event_id:
            raise MembershipStripeError("STRIPE_EVENT_ID_REQUIRED")
        if event_type not in SUPPORTED_STRIPE_EVENTS:
            raise MembershipStripeError("STRIPE_EVENT_UNSUPPORTED")
        data = event.get("data")
        obj = data.get("object") if isinstance(data, dict) else None
        if not isinstance(obj, dict):
            raise MembershipStripeError("STRIPE_EVENT_OBJECT_INVALID")
        payment_event, duplicate = await self._reserve_event(event_id, event_type)
        if duplicate and payment_event.processing_status == "PROCESSED":
            return await self._duplicate_result(guild_id, payment_event)
        try:
            application = await self._apply(
                guild_id,
                payment_event.id,
                event_type,
                obj,
                event_created=_timestamp(event.get("created")) or utc_now(),
                actor_user_id=actor_user_id,
            )
            return StripeWebhookApplication(
                duplicate,
                application.discord_user_id,
                application.membership_status,
                application.should_have_role,
            )
        except MembershipStripeError as exc:
            async with self.database.session() as session:
                stored = await session.get(PaymentEvent, payment_event.id)
                if stored is not None:
                    stored.processing_status = "FAILED"
                    stored.error_type = exc.code
                    stored.processed_at = utc_now()
                    await session.commit()
            raise

    async def _reserve_event(self, event_id: str, event_type: str) -> tuple[PaymentEvent, bool]:
        async with self.database.session() as session:
            existing = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "stripe",
                    PaymentEvent.provider_event_id == event_id,
                )
            )
            if existing is not None:
                if existing.processing_status == "FAILED":
                    existing.processing_status = "PENDING"
                    existing.error_type = None
                    await session.commit()
                return existing, True
            stored = PaymentEvent(
                provider="stripe",
                provider_event_id=event_id[:255],
                event_type=event_type,
                processing_status="PENDING",
            )
            session.add(stored)
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                existing = await session.scalar(
                    select(PaymentEvent).where(
                        PaymentEvent.provider == "stripe",
                        PaymentEvent.provider_event_id == event_id,
                    )
                )
                if existing is None:
                    raise MembershipStripeError("STRIPE_EVENT_RESERVATION_FAILED") from None
                return existing, True
            return stored, False

    async def _apply(
        self,
        guild_id: int,
        payment_event_id: uuid.UUID,
        event_type: str,
        obj: dict[str, Any],
        *,
        event_created: datetime,
        actor_user_id: int,
    ) -> StripeWebhookApplication:
        async with self.database.session() as session:
            stored = await session.scalar(
                select(PaymentEvent).where(PaymentEvent.id == payment_event_id).with_for_update()
            )
            if stored is None:
                raise MembershipStripeError("STRIPE_EVENT_NOT_FOUND")
            if stored.processing_status == "PROCESSED":
                entitlement = (
                    await session.get(MembershipEntitlement, stored.membership_id)
                    if stored.membership_id is not None
                    else None
                )
                if entitlement is None or stored.discord_user_id is None:
                    return StripeWebhookApplication(True, None, None, None)
                role = await self._has_access(guild_id, stored.discord_user_id)
                return StripeWebhookApplication(
                    True,
                    stored.discord_user_id,
                    entitlement.status,
                    role,
                )
            if event_type == "checkout.session.completed":
                entitlement = await self._apply_checkout(
                    session, guild_id, obj, event_created, actor_user_id
                )
            else:
                entitlement = await self._apply_subscription_event(
                    session, guild_id, event_type, obj, event_created, actor_user_id
                )
            stored.discord_user_id = entitlement.discord_user_id
            stored.membership_id = entitlement.id
            stored.processing_status = "PROCESSED"
            stored.error_type = None
            stored.processed_at = utc_now()
            await session.commit()
            role = await self._has_access(guild_id, entitlement.discord_user_id)
            return StripeWebhookApplication(
                False,
                entitlement.discord_user_id,
                entitlement.status,
                role,
            )

    async def _apply_checkout(
        self,
        session: Any,
        guild_id: int,
        obj: dict[str, Any],
        event_created: datetime,
        actor_user_id: int,
    ) -> MembershipEntitlement:
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        token = str(metadata.get("membership_session_id") or obj.get("client_reference_id") or "")
        membership_session = await session.scalar(
            select(MembershipSession).where(MembershipSession.session_id == token).with_for_update()
        )
        if membership_session is None or membership_session.guild_id != guild_id:
            raise MembershipStripeError("MEMBERSHIP_SESSION_NOT_FOUND")
        if membership_session.provider != "stripe":
            raise MembershipStripeError("MEMBERSHIP_SESSION_PROVIDER_MISMATCH")
        if membership_session.used_at is not None:
            existing = await session.scalar(
                select(MembershipEntitlement).where(
                    MembershipEntitlement.provider == "stripe",
                    MembershipEntitlement.provider_checkout_session_id == str(obj.get("id")),
                )
            )
            if existing is not None:
                return existing
            raise MembershipStripeError("MEMBERSHIP_SESSION_ALREADY_USED")
        # A signed completed Stripe Session is authoritative even if the short
        # local URL-reuse window elapsed while the customer was paying.
        user_id = _positive_int(metadata.get("discord_user_id"))
        plan_type = str(metadata.get("membership_type") or "")
        pricing_version = str(metadata.get("pricing_version") or "")
        if (
            user_id != membership_session.discord_user_id
            or plan_type != membership_session.membership_type
            or pricing_version != membership_session.pricing_version
        ):
            raise MembershipStripeError("MEMBERSHIP_SESSION_METADATA_MISMATCH")
        price = await session.get(MembershipPrice, membership_session.membership_price_id)
        if price is None or price.pricing_version != pricing_version:
            raise MembershipStripeError("MEMBERSHIP_PRICE_NOT_FOUND")
        checkout_id = str(obj.get("id") or "")
        customer_id = _object_id(obj.get("customer"))
        subscription_id = _object_id(obj.get("subscription"))
        if plan_type == MembershipPlanType.DAY_PASS.value:
            if str(obj.get("payment_status") or "") not in {"paid", "no_payment_required"}:
                raise MembershipStripeError("DAY_PASS_PAYMENT_NOT_COMPLETE")
            window = self.calendar.trading_window(event_created, 1)
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.DAY_PASS.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=event_created,
                ends_at=window.expires_at,
                first_trading_day=window.first_trading_day,
                last_trading_day=window.last_trading_day,
            )
        elif plan_type == MembershipPlanType.MONTHLY.value:
            if not subscription_id:
                raise MembershipStripeError("STRIPE_SUBSCRIPTION_ID_REQUIRED")
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.MONTHLY.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=event_created,
                ends_at=None,
                provider_subscription_id=subscription_id,
            )
        else:
            raise MembershipStripeError("MEMBERSHIP_PLAN_INVALID")
        entitlement.membership_price_id = price.id
        entitlement.pricing_version = price.pricing_version
        entitlement.stripe_price_id = price.stripe_price_id
        entitlement.unit_amount_at_signup = price.unit_amount
        entitlement.currency = price.currency
        entitlement.provider = "stripe"
        entitlement.provider_customer_id = customer_id
        entitlement.provider_checkout_session_id = checkout_id
        session.add(entitlement)
        await session.flush()
        membership_session.used_at = event_created
        membership_session.provider_checkout_session_id = checkout_id
        self._audit(session, entitlement, "STRIPE_CHECKOUT_COMPLETED", actor_user_id)
        return entitlement

    async def _apply_subscription_event(
        self,
        session: Any,
        guild_id: int,
        event_type: str,
        obj: dict[str, Any],
        event_created: datetime,
        actor_user_id: int,
    ) -> MembershipEntitlement:
        subscription_id = _subscription_id(obj)
        if not subscription_id:
            raise MembershipStripeError("STRIPE_SUBSCRIPTION_ID_REQUIRED")
        entitlement = await session.scalar(
            select(MembershipEntitlement)
            .where(
                MembershipEntitlement.guild_id == guild_id,
                MembershipEntitlement.provider == "stripe",
                MembershipEntitlement.provider_subscription_id == subscription_id,
            )
            .with_for_update()
        )
        if entitlement is None:
            raise MembershipStripeError("STRIPE_SUBSCRIPTION_NOT_LINKED")
        period_end = _subscription_period_end(obj)
        if event_type == "invoice.paid":
            entitlement.status = EntitlementStatus.ACTIVE.value
            entitlement.cancel_at_period_end = False
            entitlement.ends_at = period_end or entitlement.ends_at
            action = "STRIPE_INVOICE_PAID"
        elif event_type == "invoice.payment_failed":
            entitlement.status = EntitlementStatus.PAST_DUE.value
            action = "STRIPE_INVOICE_PAYMENT_FAILED"
        elif event_type == "customer.subscription.deleted":
            entitlement.status = EntitlementStatus.CANCELLED.value
            entitlement.cancel_at_period_end = False
            entitlement.ends_at = event_created
            action = "STRIPE_SUBSCRIPTION_DELETED"
        else:
            stripe_status = str(obj.get("status") or "").lower()
            cancel_at_end = bool(obj.get("cancel_at_period_end", False))
            if stripe_status in {"active", "trialing"}:
                entitlement.status = (
                    EntitlementStatus.CANCEL_AT_PERIOD_END.value
                    if cancel_at_end
                    else EntitlementStatus.ACTIVE.value
                )
            elif stripe_status in {"past_due", "incomplete"}:
                entitlement.status = EntitlementStatus.PAST_DUE.value
            elif stripe_status in {"canceled", "unpaid", "incomplete_expired", "paused"}:
                entitlement.status = EntitlementStatus.CANCELLED.value
                entitlement.ends_at = event_created
            else:
                raise MembershipStripeError("STRIPE_SUBSCRIPTION_STATUS_UNSUPPORTED")
            entitlement.cancel_at_period_end = cancel_at_end
            entitlement.ends_at = period_end or entitlement.ends_at
            action = "STRIPE_SUBSCRIPTION_UPDATED"
        entitlement.provider_customer_id = (
            _object_id(obj.get("customer")) or entitlement.provider_customer_id
        )
        entitlement.version += 1
        self._audit(session, entitlement, action, actor_user_id)
        return entitlement

    async def _duplicate_result(
        self, guild_id: int, payment_event: PaymentEvent
    ) -> StripeWebhookApplication:
        if payment_event.discord_user_id is None:
            return StripeWebhookApplication(True, None, None, None)
        status = None
        if payment_event.membership_id is not None:
            async with self.database.session() as session:
                entitlement = await session.get(MembershipEntitlement, payment_event.membership_id)
                status = entitlement.status if entitlement is not None else None
        return StripeWebhookApplication(
            True,
            payment_event.discord_user_id,
            status,
            await self._has_access(guild_id, payment_event.discord_user_id),
        )

    async def _has_access(self, guild_id: int, user_id: int) -> bool:
        now = utc_now()
        async with self.database.session() as session:
            entitlement = await session.scalar(
                select(MembershipEntitlement.id).where(
                    MembershipEntitlement.guild_id == guild_id,
                    MembershipEntitlement.discord_user_id == user_id,
                    MembershipEntitlement.status.in_(ACCESS_STATUSES),
                    (
                        (MembershipEntitlement.status == EntitlementStatus.PAST_DUE.value)
                        | MembershipEntitlement.ends_at.is_(None)
                        | (MembershipEntitlement.ends_at > now)
                    ),
                )
            )
            return entitlement is not None

    @staticmethod
    def _audit(
        session: Any,
        entitlement: MembershipEntitlement,
        action: str,
        actor_user_id: int,
    ) -> None:
        session.add(
            AuditLog(
                guild_id=entitlement.guild_id,
                actor_user_id=actor_user_id,
                action_type=action,
                entity_type="membership_entitlement",
                entity_id=str(entitlement.id),
                after_json={
                    "entitlement_type": entitlement.entitlement_type,
                    "status": entitlement.status,
                    "pricing_version": entitlement.pricing_version,
                    "ends_at": entitlement.ends_at.isoformat() if entitlement.ends_at else None,
                },
            )
        )


def _positive_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise MembershipStripeError("STRIPE_DISCORD_USER_ID_INVALID") from exc
    if parsed <= 0:
        raise MembershipStripeError("STRIPE_DISCORD_USER_ID_INVALID")
    return parsed


def _object_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        parsed = str(value.get("id") or "")
        return parsed or None
    return None


def _subscription_id(obj: dict[str, Any]) -> str | None:
    direct = _object_id(obj.get("subscription"))
    if direct:
        return direct
    if str(obj.get("object") or "") == "subscription":
        return _object_id(obj.get("id"))
    parent = obj.get("parent")
    details = parent.get("subscription_details") if isinstance(parent, dict) else None
    if isinstance(details, dict):
        return _object_id(details.get("subscription"))
    return None


def _subscription_period_end(obj: dict[str, Any]) -> datetime | None:
    direct = _timestamp(obj.get("current_period_end"))
    if direct:
        return direct
    lines = obj.get("lines")
    data = lines.get("data") if isinstance(lines, dict) else None
    if isinstance(data, list):
        values = []
        for line in data:
            period = line.get("period") if isinstance(line, dict) else None
            parsed = _timestamp(period.get("end")) if isinstance(period, dict) else None
            if parsed:
                values.append(parsed)
        return max(values) if values else None
    items = obj.get("items")
    item_data = items.get("data") if isinstance(items, dict) else None
    if isinstance(item_data, list):
        values = [
            parsed
            for item in item_data
            if isinstance(item, dict)
            if (parsed := _timestamp(item.get("current_period_end"))) is not None
        ]
        return max(values) if values else None
    return None


def _timestamp(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MembershipStripeError("STRIPE_TIMESTAMP_INVALID") from exc
        return _aware(parsed)
    raise MembershipStripeError("STRIPE_TIMESTAMP_INVALID")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
