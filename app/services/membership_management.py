from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models import (
    AuditLog,
    Membership,
    MembershipEntitlement,
    MembershipEvent,
    ScheduledJob,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import (
    EntitlementStatus,
    EntitlementType,
    JobStatus,
    MembershipExtensionType,
)
from app.services.membership_access import (
    ACCESS_STATUSES,
    AccessSnapshot,
    MembershipAccessError,
    MembershipAccessService,
    MembershipAcknowledgementService,
)
from app.services.membership_stripe import MembershipStripeError, MembershipStripeService
from app.services.trading_calendar import TradingCalendarService


class MembershipError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class MembershipValidationError(MembershipError):
    pass


@dataclass(frozen=True, slots=True)
class MembershipSnapshot:
    id: uuid.UUID
    guild_id: int
    user_id: int
    status: str
    source: str
    provider: str | None
    provider_customer_id: str | None
    provider_subscription_id: str | None
    starts_at: datetime
    ends_at: datetime | None
    cancel_at_period_end: bool
    version: int
    entitlement_count: int = 1

    @property
    def is_active(self) -> bool:
        if self.status == EntitlementStatus.PAST_DUE.value:
            return True
        end = _aware(self.ends_at) if self.ends_at is not None else None
        return self.status in ACCESS_STATUSES and (end is None or end > utc_now())


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class MembershipManagementService:
    """Manager-facing compatibility adapter over the multi-entitlement access model."""

    def __init__(
        self,
        database: Database,
        access: MembershipAccessService | None = None,
        stripe: MembershipStripeService | None = None,
    ) -> None:
        self.database = database
        self.access = access or MembershipAccessService(
            database,
            TradingCalendarService(),
            MembershipAcknowledgementService(database),
        )
        self.stripe = stripe

    async def get(self, guild_id: int, user_id: int) -> MembershipSnapshot | None:
        return self._aggregate(await self.access.status(guild_id, user_id))

    async def grant(
        self,
        guild_id: int,
        user_id: int,
        *,
        days: int | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        try:
            await self.access.grant(
                guild_id,
                user_id,
                days=days,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
            )
        except MembershipAccessError as exc:
            raise MembershipValidationError(exc.code) from exc
        return self._required(await self.get(guild_id, user_id))

    async def extend(
        self,
        guild_id: int,
        user_id: int,
        *,
        days: int | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        if days is None:
            raise MembershipValidationError("EXTENSION_TYPE_REQUIRED")
        return await self.extend_access(
            guild_id,
            user_id,
            extension_type=MembershipExtensionType.CALENDAR_DAYS.value,
            amount=days,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
        )

    async def extend_access(
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
    ) -> MembershipSnapshot:
        try:
            await self.access.extend(
                guild_id,
                user_id,
                extension_type=extension_type,
                amount=amount,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                reason=reason,
                custom_expiry=custom_expiry,
            )
        except MembershipAccessError as exc:
            raise MembershipValidationError(exc.code) from exc
        return self._required(await self.get(guild_id, user_id))

    async def cancel_at_expiry(
        self,
        guild_id: int,
        user_id: int,
        *,
        ends_at: datetime | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        monthly_requested = False
        if self.stripe is not None:
            try:
                monthly_requested = await self.stripe.manager_cancel_monthly(
                    guild_id, user_id, immediately=False
                )
            except MembershipStripeError as exc:
                raise MembershipValidationError(exc.code) from exc
        try:
            await self.access.cancel_at_expiry(
                guild_id,
                user_id,
                ends_at=ends_at,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
            )
        except MembershipAccessError as exc:
            if not monthly_requested or exc.code != "EXPIRING_ACCESS_NOT_FOUND":
                raise MembershipValidationError(exc.code) from exc
        return self._required(await self.get(guild_id, user_id))

    async def remove(
        self,
        guild_id: int,
        user_id: int,
        *,
        actor_user_id: int,
        interaction_id: int | None,
        reason: str = "manager_revoke",
    ) -> MembershipSnapshot:
        if self.stripe is not None:
            try:
                await self.stripe.manager_cancel_monthly(guild_id, user_id, immediately=True)
            except MembershipStripeError as exc:
                raise MembershipValidationError(exc.code) from exc
        try:
            await self.access.revoke(
                guild_id,
                user_id,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                reason=reason,
            )
        except MembershipAccessError as exc:
            raise MembershipValidationError(exc.code) from exc
        return self._required(await self.get(guild_id, user_id))

    async def sync_manual_role(
        self,
        guild_id: int,
        user_id: int,
        *,
        has_role: bool,
        actor_user_id: int,
    ) -> MembershipSnapshot | None:
        if has_role:
            await self.access.add_manual(guild_id, user_id, actor_user_id=actor_user_id)
            return await self.get(guild_id, user_id)
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(MembershipEntitlement)
                    .where(
                        MembershipEntitlement.guild_id == guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.entitlement_type == EntitlementType.MANUAL.value,
                        MembershipEntitlement.status.in_(ACCESS_STATUSES),
                    )
                    .with_for_update()
                )
            ).all()
            for entitlement in rows:
                entitlement.status = EntitlementStatus.REVOKED.value
                entitlement.ends_at = now
                entitlement.reason = "manual_role_removed"
                entitlement.version += 1
                session.add(
                    AuditLog(
                        guild_id=guild_id,
                        actor_user_id=actor_user_id,
                        action_type="MEMBERSHIP_ROLE_REMOVED",
                        entity_type="membership_entitlement",
                        entity_id=str(entitlement.id),
                    )
                )
            await session.commit()
        return await self.get(guild_id, user_id)

    async def import_role_holder(
        self, guild_id: int, user_id: int, *, actor_user_id: int
    ) -> MembershipSnapshot | None:
        existing = await self.get(guild_id, user_id)
        if existing is not None and existing.is_active:
            return existing
        await self.access.add_manual(guild_id, user_id, actor_user_id=actor_user_id)
        return await self.get(guild_id, user_id)

    async def active_user_ids(self, guild_id: int) -> set[int]:
        return await self.access.active_user_ids(guild_id)

    async def process_due(self, guild_id: int, *, actor_user_id: int) -> list[int]:
        return await self.access.expire_due(guild_id, actor_user_id=actor_user_id)

    @staticmethod
    def _aggregate(access: AccessSnapshot) -> MembershipSnapshot | None:
        if not access.entitlements:
            return None
        active = [item for item in access.entitlements if item.is_active]
        representative = (active or list(access.entitlements))[-1]
        starts_at = min(item.starts_at for item in access.entitlements)
        effective_expiry = access.effective_expiry if active else representative.ends_at
        status = EntitlementStatus.ACTIVE.value if access.has_access else representative.status
        if active and all(item.status == EntitlementStatus.PAST_DUE.value for item in active):
            status = EntitlementStatus.PAST_DUE.value
        return MembershipSnapshot(
            id=representative.id,
            guild_id=access.guild_id,
            user_id=access.user_id,
            status=status,
            source=" + ".join(sorted({item.entitlement_type for item in active}))
            if active
            else representative.entitlement_type,
            provider="stripe" if any(item.provider_subscription_id for item in active) else None,
            provider_customer_id=next(
                (
                    item.provider_customer_id
                    for item in reversed(active)
                    if item.provider_customer_id
                ),
                None,
            ),
            provider_subscription_id=next(
                (
                    item.provider_subscription_id
                    for item in reversed(active)
                    if item.provider_subscription_id
                ),
                None,
            ),
            starts_at=starts_at,
            ends_at=effective_expiry,
            cancel_at_period_end=any(item.cancel_at_period_end for item in active),
            version=max(item.version for item in access.entitlements),
            entitlement_count=len(access.entitlements),
        )

    @staticmethod
    def _required(snapshot: MembershipSnapshot | None) -> MembershipSnapshot:
        if snapshot is None:
            raise MembershipValidationError("MEMBERSHIP_NOT_FOUND")
        return snapshot

    # Compatibility helpers retained for replaying pre-0015 provider events.
    @staticmethod
    def _payload(membership: Membership | None) -> dict[str, object] | None:
        if membership is None:
            return None
        return {
            "status": membership.status,
            "source": membership.source,
            "provider": membership.provider,
            "provider_customer_id": membership.provider_customer_id,
            "provider_subscription_id": membership.provider_subscription_id,
            "starts_at": membership.starts_at.isoformat(),
            "ends_at": membership.ends_at.isoformat() if membership.ends_at else None,
            "cancel_at_period_end": membership.cancel_at_period_end,
            "version": membership.version,
        }

    @classmethod
    async def _record_change(
        cls,
        session: object,
        membership: Membership,
        *,
        action: str,
        actor_user_id: int,
        interaction_id: int | None,
        before: dict[str, object] | None,
        reason: str | None,
    ) -> None:
        after = cls._payload(membership)
        session.add(
            MembershipEvent(
                membership_id=membership.id,
                action=action,
                source=membership.source,
                actor_user_id=actor_user_id,
                before_json=before,
                after_json=after,
                reason=reason,
            )
        )
        session.add(
            AuditLog(
                guild_id=membership.guild_id,
                actor_user_id=actor_user_id,
                action_type=action,
                entity_type="membership",
                entity_id=str(membership.id),
                before_json=before,
                after_json=after,
                discord_interaction_id=interaction_id,
            )
        )

    @staticmethod
    async def _cancel_jobs(session: object, membership_id: uuid.UUID) -> None:
        jobs = (
            await session.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.dedupe_key.like(f"membership-expiry:{membership_id}:%"),
                    ScheduledJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value]),
                )
            )
        ).all()
        for job in jobs:
            job.status = JobStatus.CANCELLED.value

    @classmethod
    async def _reschedule(cls, session: object, membership: Membership) -> None:
        await cls._cancel_jobs(session, membership.id)
        if membership.ends_at is None:
            return
        session.add(
            ScheduledJob(
                guild_id=membership.guild_id,
                job_type="MEMBERSHIP_EXPIRE",
                dedupe_key=f"membership-expiry:{membership.id}:v{membership.version}",
                status=JobStatus.PENDING.value,
                run_at=membership.ends_at,
                attempts=0,
                max_attempts=5,
                payload={"membership_id": str(membership.id), "user_id": membership.user_id},
            )
        )
