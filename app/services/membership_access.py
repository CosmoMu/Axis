from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AccessApplication,
    AuditLog,
    MembershipAcknowledgement,
    MembershipEntitlement,
    MembershipPrice,
    MembershipTrial,
    NewcomerProfile,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import (
    AccessApplicationStatus,
    AcknowledgementDocumentType,
    EntitlementStatus,
    EntitlementType,
    MembershipExtensionType,
    MembershipPlanType,
)
from app.services.trading_calendar import TradingCalendarService

RISK_DISCLOSURE_VERSION = "AXIS_APPLICATION_RISK_V1"
ACCESS_STATUSES = {
    EntitlementStatus.ACTIVE.value,
    EntitlementStatus.PAST_DUE.value,
    EntitlementStatus.CANCEL_AT_PERIOD_END.value,
}


class MembershipAccessError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    id: uuid.UUID
    plan_type: str
    pricing_version: str
    stripe_product_id: str | None
    stripe_price_id: str | None
    unit_amount: int
    currency: str
    billing_interval: str | None

    @property
    def display_amount(self) -> str:
        return f"${Decimal(self.unit_amount) / Decimal(100):,.2f}"


@dataclass(frozen=True, slots=True)
class EntitlementSnapshot:
    id: uuid.UUID
    guild_id: int
    user_id: int
    entitlement_type: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    first_trading_day: object | None
    last_trading_day: object | None
    pricing_version: str | None
    unit_amount_at_signup: int | None
    provider_customer_id: str | None
    provider_subscription_id: str | None
    cancel_at_period_end: bool
    version: int

    @property
    def is_active(self) -> bool:
        now = utc_now()
        if self.status == EntitlementStatus.PAST_DUE.value:
            return True
        return self.status in ACCESS_STATUSES and (
            self.ends_at is None or _aware(self.ends_at) > now
        )


@dataclass(frozen=True, slots=True)
class AccessSnapshot:
    guild_id: int
    user_id: int
    entitlements: tuple[EntitlementSnapshot, ...]

    @property
    def has_access(self) -> bool:
        return any(item.is_active for item in self.entitlements)

    @property
    def effective_expiry(self) -> datetime | None:
        active = [item for item in self.entitlements if item.is_active]
        if not active or any(item.ends_at is None for item in active):
            return None
        return max(_aware(item.ends_at) for item in active if item.ends_at is not None)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class MembershipAcknowledgementService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def has_current_risk(self, user_id: int) -> bool:
        async with self.database.session() as session:
            acknowledgement = await session.scalar(
                select(MembershipAcknowledgement.id).where(
                    MembershipAcknowledgement.discord_user_id == user_id,
                    MembershipAcknowledgement.document_type
                    == AcknowledgementDocumentType.RISK_DISCLOSURE.value,
                    MembershipAcknowledgement.document_version == RISK_DISCLOSURE_VERSION,
                )
            )
            return acknowledgement is not None

    async def accept_risk(
        self,
        guild_id: int,
        user_id: int,
        *,
        interaction_id: int | None,
    ) -> bool:
        if user_id <= 0:
            raise MembershipAccessError("USER_ID_INVALID")
        async with self.database.session() as session:
            existing = await session.scalar(
                select(MembershipAcknowledgement.id).where(
                    MembershipAcknowledgement.discord_user_id == user_id,
                    MembershipAcknowledgement.document_type
                    == AcknowledgementDocumentType.RISK_DISCLOSURE.value,
                    MembershipAcknowledgement.document_version == RISK_DISCLOSURE_VERSION,
                )
            )
            if existing is not None:
                return False
            session.add(
                MembershipAcknowledgement(
                    guild_id=guild_id,
                    discord_user_id=user_id,
                    document_type=AcknowledgementDocumentType.RISK_DISCLOSURE.value,
                    document_version=RISK_DISCLOSURE_VERSION,
                    accepted_at=utc_now(),
                    discord_interaction_id=interaction_id,
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return False
            return True


class MembershipPriceCatalog:
    def __init__(self, database: Database, *, environment: str = "TEST") -> None:
        normalized = environment.strip().upper()
        if normalized not in {"TEST", "LIVE"}:
            raise MembershipAccessError("PAYMENT_ENVIRONMENT_INVALID")
        self.database = database
        self.environment = normalized

    async def current(self, plan_type: str) -> PriceSnapshot:
        if plan_type not in {item.value for item in MembershipPlanType}:
            raise MembershipAccessError("MEMBERSHIP_PLAN_INVALID")
        async with self.database.session() as session:
            price = await session.scalar(
                select(MembershipPrice).where(
                    MembershipPrice.environment == self.environment,
                    MembershipPrice.plan_type == plan_type,
                    MembershipPrice.is_current.is_(True),
                    MembershipPrice.is_active.is_(True),
                )
            )
            if price is None:
                raise MembershipAccessError("MEMBERSHIP_PRICE_NOT_CONFIGURED")
            return self._snapshot(price)

    async def current_offers(self) -> dict[str, PriceSnapshot]:
        async with self.database.session() as session:
            prices = (
                await session.scalars(
                    select(MembershipPrice).where(
                        MembershipPrice.environment == self.environment,
                        MembershipPrice.is_current.is_(True),
                        MembershipPrice.is_active.is_(True),
                    )
                )
            ).all()
            return {item.plan_type: self._snapshot(item) for item in prices}

    async def bind_stripe_ids(
        self,
        plan_type: str,
        pricing_version: str,
        *,
        product_id: str | None,
        price_id: str | None,
    ) -> None:
        if not product_id and not price_id:
            return
        async with self.database.session() as session:
            price = await session.scalar(
                select(MembershipPrice)
                .where(
                    MembershipPrice.environment == self.environment,
                    MembershipPrice.plan_type == plan_type,
                    MembershipPrice.pricing_version == pricing_version,
                )
                .with_for_update()
            )
            if price is None:
                raise MembershipAccessError("MEMBERSHIP_PRICE_VERSION_NOT_FOUND")
            for current, configured in (
                (price.stripe_product_id, product_id),
                (price.stripe_price_id, price_id),
            ):
                if current and configured and current != configured:
                    raise MembershipAccessError("MEMBERSHIP_PRICE_ID_IMMUTABLE")
            price.stripe_product_id = price.stripe_product_id or product_id
            price.stripe_price_id = price.stripe_price_id or price_id
            await session.commit()

    @staticmethod
    def _snapshot(price: MembershipPrice) -> PriceSnapshot:
        return PriceSnapshot(
            id=price.id,
            plan_type=price.plan_type,
            pricing_version=price.pricing_version,
            stripe_product_id=price.stripe_product_id,
            stripe_price_id=price.stripe_price_id,
            unit_amount=price.unit_amount,
            currency=price.currency,
            billing_interval=price.billing_interval,
        )


class MembershipAccessService:
    def __init__(
        self,
        database: Database,
        calendar: TradingCalendarService,
        acknowledgements: MembershipAcknowledgementService,
        *,
        free_trial_enabled: bool = True,
        free_trial_trading_days: int = 3,
    ) -> None:
        if free_trial_trading_days <= 0:
            raise ValueError("free_trial_trading_days must be positive")
        self.database = database
        self.calendar = calendar
        self.acknowledgements = acknowledgements
        self.free_trial_enabled = free_trial_enabled
        self.free_trial_trading_days = free_trial_trading_days

    async def status(self, guild_id: int, user_id: int) -> AccessSnapshot:
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                    )
                    .order_by(MembershipEntitlement.created_at)
                )
            ).all()
            return AccessSnapshot(
                guild_id,
                user_id,
                tuple(self._snapshot(item) for item in rows),
            )

    async def active_user_ids(self, guild_id: int) -> set[int]:
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement.discord_user_id)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                        (
                            (MembershipEntitlement.status == EntitlementStatus.PAST_DUE.value)
                            | MembershipEntitlement.ends_at.is_(None)
                            | (MembershipEntitlement.ends_at > now)
                        ),
                    )
                    .distinct()
                )
            ).all()
            return set(rows)

    async def should_have_access(self, guild_id: int, user_id: int) -> bool:
        return (await self.status(guild_id, user_id)).has_access

    async def free_trial_claim_state(
        self,
        guild_id: int,
        user_id: int,
        *,
        now: datetime | None = None,
    ) -> str:
        """Inspect eligibility without granting access or consuming the one-time trial."""
        if not self.free_trial_enabled:
            return "DISABLED"
        checked_at = _aware(now or utc_now())
        async with self.database.session() as session:
            approved = await session.scalar(
                select(NewcomerProfile.approved_at).where(
                    NewcomerProfile.guild_id == guild_id,
                    NewcomerProfile.discord_user_id == user_id,
                )
            )
            if approved is None:
                return "APPROVAL_REQUIRED"
            existing = await session.scalar(
                select(MembershipTrial.id).where(
                    MembershipTrial.discord_user_id == user_id,
                    MembershipTrial.trial_type == EntitlementType.FREE_TRIAL.value,
                )
            )
            if existing is not None:
                return "USED"
            active = await session.scalar(
                select(MembershipEntitlement.id).where(
                    MembershipEntitlement.guild_id == guild_id,
                    MembershipEntitlement.discord_user_id == user_id,
                    MembershipEntitlement.status.in_(ACCESS_STATUSES),
                    (
                        (MembershipEntitlement.status == EntitlementStatus.PAST_DUE.value)
                        | MembershipEntitlement.ends_at.is_(None)
                        | (MembershipEntitlement.ends_at > checked_at)
                    ),
                )
            )
            return "ACCESS_ACTIVE" if active is not None else "ELIGIBLE"

    async def claim_free_trial(
        self,
        guild_id: int,
        user_id: int,
        *,
        interaction_id: int | None,
        application_id: uuid.UUID | None = None,
        approved_by_user_id: int | None = None,
        now: datetime | None = None,
    ) -> EntitlementSnapshot:
        if not self.free_trial_enabled:
            raise MembershipAccessError("FREE_TRIAL_DISABLED")
        if not await self.acknowledgements.has_current_risk(user_id):
            raise MembershipAccessError("RISK_ACKNOWLEDGEMENT_REQUIRED")
        claimed_at = _aware(now or utc_now())
        async with self.database.session() as session:
            application = (
                await session.get(AccessApplication, application_id)
                if application_id is not None
                else None
            )
            if (
                application is None
                or application.guild_id != guild_id
                or application.discord_user_id != user_id
                or application.status != AccessApplicationStatus.APPROVED.value
            ):
                raise MembershipAccessError("ACCESS_APPROVAL_REQUIRED")
            window = self.calendar.trading_window(
                claimed_at,
                self.free_trial_trading_days,
            )
            expires_at = window.expires_at
            existing = await session.scalar(
                select(MembershipTrial.id).where(
                    MembershipTrial.discord_user_id == user_id,
                    MembershipTrial.trial_type == EntitlementType.FREE_TRIAL.value,
                )
            )
            if existing is not None:
                session.add(
                    AuditLog(
                        guild_id=guild_id,
                        actor_user_id=approved_by_user_id or user_id,
                        action_type="FREE_TRIAL_DUPLICATE_BLOCKED",
                        entity_type="membership_trial",
                        entity_id=str(user_id),
                        after_json={"application_id": str(application_id)},
                        discord_interaction_id=interaction_id,
                    )
                )
                await session.commit()
                raise MembershipAccessError("FREE_TRIAL_ALREADY_CLAIMED")
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.FREE_TRIAL.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=claimed_at,
                ends_at=expires_at,
                first_trading_day=window.first_trading_day,
                last_trading_day=window.last_trading_day,
            )
            session.add(entitlement)
            await session.flush()
            session.add(
                MembershipTrial(
                    guild_id=guild_id,
                    discord_user_id=user_id,
                    trial_type=EntitlementType.FREE_TRIAL.value,
                    duration_unit="TRADING_DAY",
                    duration_amount=self.free_trial_trading_days,
                    calendar_days_granted=None,
                    trading_days_granted=self.free_trial_trading_days,
                    claimed_at=claimed_at,
                    started_at=claimed_at,
                    first_trading_day=window.first_trading_day,
                    last_trading_day=window.last_trading_day,
                    expires_at=expires_at,
                    status=EntitlementStatus.ACTIVE.value,
                    entitlement_id=entitlement.id,
                    application_id=application_id,
                    approved_by_user_id=approved_by_user_id,
                )
            )
            self._audit(
                session,
                entitlement,
                "FREE_TRIAL_CREATED",
                actor_user_id=approved_by_user_id or user_id,
                interaction_id=interaction_id,
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                async with self.database.session() as audit_session:
                    audit_session.add(
                        AuditLog(
                            guild_id=guild_id,
                            actor_user_id=approved_by_user_id or user_id,
                            action_type="FREE_TRIAL_DUPLICATE_BLOCKED",
                            entity_type="membership_trial",
                            entity_id=str(user_id),
                            after_json={"application_id": str(application_id)},
                            discord_interaction_id=interaction_id,
                        )
                    )
                    await audit_session.commit()
                raise MembershipAccessError("FREE_TRIAL_ALREADY_CLAIMED") from exc
            return self._snapshot(entitlement)

    async def grant(
        self,
        guild_id: int,
        user_id: int,
        *,
        days: int | None,
        actor_user_id: int,
        interaction_id: int | None,
        reason: str | None = None,
    ) -> EntitlementSnapshot:
        if days is not None and not 1 <= days <= 3650:
            raise MembershipAccessError("DURATION_INVALID")
        now = utc_now()
        ends_at = None if days is None else self.calendar.calendar_expiry(now, days=days)
        async with self.database.session() as session:
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.GIFT.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=now,
                ends_at=ends_at,
                granted_by_user_id=actor_user_id,
                reason=(reason or "manager_gift")[:500],
            )
            session.add(entitlement)
            await session.flush()
            self._audit(session, entitlement, "MEMBERSHIP_GRANTED", actor_user_id, interaction_id)
            await session.commit()
            return self._snapshot(entitlement)

    async def add_manual(
        self, guild_id: int, user_id: int, *, actor_user_id: int
    ) -> EntitlementSnapshot:
        now = utc_now()
        async with self.database.session() as session:
            current = await session.scalar(
                select(MembershipEntitlement).where(
                    MembershipEntitlement.guild_id == guild_id,
                    MembershipEntitlement.discord_user_id == user_id,
                    MembershipEntitlement.entitlement_type == EntitlementType.MANUAL.value,
                    MembershipEntitlement.status.in_(ACCESS_STATUSES),
                )
            )
            if current is not None:
                return self._snapshot(current)
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.MANUAL.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=now,
                ends_at=None,
                granted_by_user_id=actor_user_id,
                reason="manual_role_added",
            )
            session.add(entitlement)
            await session.flush()
            self._audit(session, entitlement, "MEMBERSHIP_ROLE_ADDED", actor_user_id, None)
            await session.commit()
            return self._snapshot(entitlement)

    async def extend(
        self,
        guild_id: int,
        user_id: int,
        *,
        extension_type: str,
        amount: int | None,
        actor_user_id: int,
        interaction_id: int | None,
        reason: str | None = None,
        custom_expiry: datetime | None = None,
        now: datetime | None = None,
    ) -> EntitlementSnapshot:
        valid_types = {item.value for item in MembershipExtensionType}
        if extension_type not in valid_types:
            raise MembershipAccessError("EXTENSION_TYPE_INVALID")
        if extension_type != MembershipExtensionType.CUSTOM.value and (
            amount is None or amount <= 0
        ):
            raise MembershipAccessError("EXTENSION_AMOUNT_INVALID")
        activated_at = now or utc_now()
        current = await self.status(guild_id, user_id)
        active = [item for item in current.entitlements if item.is_active]
        if any(item.ends_at is None for item in active):
            raise MembershipAccessError("LIFETIME_ACCESS_ALREADY_ACTIVE")
        old_expiry = current.effective_expiry
        source_id = None
        if old_expiry is not None:
            source_id = max(
                (item for item in active if item.ends_at is not None),
                key=lambda item: _aware(item.ends_at),
            ).id
        base = old_expiry if old_expiry and old_expiry > activated_at else activated_at
        first_day = last_day = None
        if extension_type == MembershipExtensionType.TRADING_DAYS.value:
            window = self.calendar.trading_window(
                activated_at,
                amount or 0,
                continue_after=old_expiry,
            )
            new_expiry = window.expires_at
            first_day, last_day = window.first_trading_day, window.last_trading_day
        elif extension_type == MembershipExtensionType.CALENDAR_DAYS.value:
            new_expiry = self.calendar.calendar_expiry(base, days=amount or 0)
        elif extension_type == MembershipExtensionType.CALENDAR_MONTH.value:
            new_expiry = self.calendar.calendar_expiry(base, months=amount or 0)
        else:
            if custom_expiry is None or _aware(custom_expiry) <= activated_at:
                raise MembershipAccessError("CUSTOM_EXPIRY_INVALID")
            new_expiry = _aware(custom_expiry)
        async with self.database.session() as session:
            entitlement = MembershipEntitlement(
                guild_id=guild_id,
                discord_user_id=user_id,
                entitlement_type=EntitlementType.MANUAL_EXTENSION.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=activated_at,
                ends_at=new_expiry,
                first_trading_day=first_day,
                last_trading_day=last_day,
                source_entitlement_id=source_id,
                granted_by_user_id=actor_user_id,
                extension_type=extension_type,
                extension_amount=amount,
                old_effective_expiry=old_expiry,
                new_effective_expiry=new_expiry,
                reason=(reason or "manager_extension")[:500],
            )
            session.add(entitlement)
            await session.flush()
            self._audit(session, entitlement, "MEMBERSHIP_EXTENDED", actor_user_id, interaction_id)
            await session.commit()
            return self._snapshot(entitlement)

    async def cancel_at_expiry(
        self,
        guild_id: int,
        user_id: int,
        *,
        ends_at: datetime | None = None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> AccessSnapshot:
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                        MembershipEntitlement.entitlement_type != EntitlementType.MONTHLY.value,
                    )
                    .with_for_update()
                )
            ).all()
            if not rows:
                raise MembershipAccessError("EXPIRING_ACCESS_NOT_FOUND")
            for entitlement in rows:
                if entitlement.ends_at is None:
                    if ends_at is None or _aware(ends_at) <= now:
                        raise MembershipAccessError("EXPIRY_REQUIRED_FOR_LIFETIME")
                    entitlement.ends_at = _aware(ends_at)
                entitlement.status = EntitlementStatus.CANCEL_AT_PERIOD_END.value
                entitlement.cancel_at_period_end = True
                entitlement.version += 1
                self._audit(
                    session,
                    entitlement,
                    "MEMBERSHIP_CANCEL_AT_EXPIRY",
                    actor_user_id,
                    interaction_id,
                )
            await session.commit()
        return await self.status(guild_id, user_id)

    async def revoke(
        self,
        guild_id: int,
        user_id: int,
        *,
        actor_user_id: int,
        interaction_id: int | None,
        reason: str,
    ) -> AccessSnapshot:
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                    )
                    .with_for_update()
                )
            ).all()
            if not rows:
                raise MembershipAccessError("MEMBERSHIP_NOT_FOUND")
            for entitlement in rows:
                entitlement.status = EntitlementStatus.REVOKED.value
                entitlement.ends_at = now
                entitlement.cancel_at_period_end = False
                entitlement.reason = reason[:500]
                entitlement.version += 1
                self._audit(
                    session,
                    entitlement,
                    "MEMBERSHIP_REVOKED",
                    actor_user_id,
                    interaction_id,
                )
            await session.commit()
        return await self.status(guild_id, user_id)

    async def expire_due(self, guild_id: int, *, actor_user_id: int) -> list[int]:
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.status.in_(
                            {
                                EntitlementStatus.ACTIVE.value,
                                EntitlementStatus.CANCEL_AT_PERIOD_END.value,
                            }
                        ),
                        MembershipEntitlement.ends_at.is_not(None),
                        MembershipEntitlement.ends_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                )
            ).all()
            users = {item.discord_user_id for item in rows}
            for entitlement in rows:
                entitlement.status = EntitlementStatus.EXPIRED.value
                entitlement.cancel_at_period_end = False
                entitlement.version += 1
                self._audit(
                    session,
                    entitlement,
                    (
                        "FREE_TRIAL_EXPIRED"
                        if entitlement.entitlement_type == EntitlementType.FREE_TRIAL.value
                        else "MEMBERSHIP_EXPIRED"
                    ),
                    actor_user_id,
                    None,
                )
            if rows:
                await session.execute(
                    update(MembershipTrial)
                    .where(MembershipTrial.entitlement_id.in_([item.id for item in rows]))
                    .values(status=EntitlementStatus.EXPIRED.value)
                )
            await session.commit()
            return sorted(users)

    async def count_active(self, guild_id: int, user_id: int) -> int:
        now = utc_now()
        async with self.database.session() as session:
            value = await session.scalar(
                select(func.count())
                .select_from(MembershipEntitlement)
                .where(
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
            return int(value or 0)

    @staticmethod
    def _snapshot(item: MembershipEntitlement) -> EntitlementSnapshot:
        return EntitlementSnapshot(
            id=item.id,
            guild_id=item.guild_id,
            user_id=item.discord_user_id,
            entitlement_type=item.entitlement_type,
            status=item.status,
            starts_at=item.starts_at,
            ends_at=item.ends_at,
            first_trading_day=item.first_trading_day,
            last_trading_day=item.last_trading_day,
            pricing_version=item.pricing_version,
            unit_amount_at_signup=item.unit_amount_at_signup,
            provider_customer_id=item.provider_customer_id,
            provider_subscription_id=item.provider_subscription_id,
            cancel_at_period_end=item.cancel_at_period_end,
            version=item.version,
        )

    @staticmethod
    def _audit(
        session: AsyncSession,
        entitlement: MembershipEntitlement,
        action: str,
        actor_user_id: int,
        interaction_id: int | None,
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
                    "ends_at": entitlement.ends_at.isoformat() if entitlement.ends_at else None,
                    "extension_type": entitlement.extension_type,
                    "extension_amount": entitlement.extension_amount,
                },
                discord_interaction_id=interaction_id,
            )
        )
