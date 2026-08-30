from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AuditLog,
    Membership,
    MembershipEvent,
    ScheduledJob,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import JobStatus, MembershipSource, MembershipStatus


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
    starts_at: datetime
    ends_at: datetime | None
    cancel_at_period_end: bool
    version: int

    @property
    def is_active(self) -> bool:
        now = datetime.now(UTC)
        end = self.ends_at
        if end is not None and end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return self.status == MembershipStatus.ACTIVE.value and (
            end is None or end > now
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class MembershipManagementService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, guild_id: int, user_id: int) -> MembershipSnapshot | None:
        async with self.database.session() as session:
            membership = await session.scalar(
                select(Membership).where(
                    Membership.guild_id == guild_id, Membership.user_id == user_id
                )
            )
            return self._snapshot(membership) if membership is not None else None

    async def grant(
        self,
        guild_id: int,
        user_id: int,
        *,
        days: int | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        self._validate_user_and_days(user_id, days)
        now = utc_now()
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            before = self._payload(membership) if membership is not None else None
            if membership is None:
                membership = Membership(
                    guild_id=guild_id,
                    user_id=user_id,
                    status=MembershipStatus.ACTIVE.value,
                    source=MembershipSource.GIFT.value,
                    starts_at=now,
                    ends_at=None if days is None else now + timedelta(days=days),
                    created_by=actor_user_id,
                )
                session.add(membership)
                action = "MEMBERSHIP_GRANTED"
            else:
                base = now
                if (
                    membership.status == MembershipStatus.ACTIVE.value
                    and membership.ends_at is not None
                    and _aware(membership.ends_at) > now
                ):
                    base = _aware(membership.ends_at)
                membership.status = MembershipStatus.ACTIVE.value
                membership.source = MembershipSource.GIFT.value
                membership.starts_at = now
                membership.ends_at = None if days is None else base + timedelta(days=days)
                membership.cancel_at_period_end = False
                membership.removal_reason = None
                membership.created_by = actor_user_id
                membership.version += 1
                action = "MEMBERSHIP_REACTIVATED"
            await session.flush()
            await self._record_change(
                session,
                membership,
                action=action,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                before=before,
                reason=None,
            )
            await self._reschedule(session, membership)
            await session.commit()
            return self._snapshot(membership)

    async def extend(
        self,
        guild_id: int,
        user_id: int,
        *,
        days: int | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        self._validate_user_and_days(user_id, days)
        now = utc_now()
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            if membership is None or membership.status != MembershipStatus.ACTIVE.value:
                raise MembershipValidationError("ACTIVE_MEMBERSHIP_NOT_FOUND")
            before = self._payload(membership)
            if days is None:
                membership.ends_at = None
            elif membership.ends_at is None:
                raise MembershipValidationError("LIFETIME_MEMBERSHIP")
            else:
                membership.ends_at = max(now, _aware(membership.ends_at)) + timedelta(
                    days=days
                )
            membership.cancel_at_period_end = False
            membership.version += 1
            await self._record_change(
                session,
                membership,
                action="MEMBERSHIP_EXTENDED",
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                before=before,
                reason=None,
            )
            await self._reschedule(session, membership)
            await session.commit()
            return self._snapshot(membership)

    async def cancel_at_expiry(
        self,
        guild_id: int,
        user_id: int,
        *,
        ends_at: datetime | None,
        actor_user_id: int,
        interaction_id: int | None,
    ) -> MembershipSnapshot:
        now = utc_now()
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            if membership is None or membership.status != MembershipStatus.ACTIVE.value:
                raise MembershipValidationError("ACTIVE_MEMBERSHIP_NOT_FOUND")
            before = self._payload(membership)
            if ends_at is not None:
                normalized_end = _aware(ends_at)
                if normalized_end <= now:
                    raise MembershipValidationError("EXPIRY_MUST_BE_FUTURE")
                membership.ends_at = normalized_end
            if membership.ends_at is None:
                raise MembershipValidationError("EXPIRY_REQUIRED_FOR_LIFETIME")
            membership.cancel_at_period_end = True
            membership.version += 1
            await self._record_change(
                session,
                membership,
                action="MEMBERSHIP_CANCEL_AT_EXPIRY",
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                before=before,
                reason=None,
            )
            await self._reschedule(session, membership)
            await session.commit()
            return self._snapshot(membership)

    async def remove(
        self,
        guild_id: int,
        user_id: int,
        *,
        actor_user_id: int,
        interaction_id: int | None,
        reason: str = "manager_revoke",
    ) -> MembershipSnapshot:
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            if membership is None:
                raise MembershipValidationError("MEMBERSHIP_NOT_FOUND")
            if membership.status == MembershipStatus.REMOVED.value:
                return self._snapshot(membership)
            before = self._payload(membership)
            membership.status = MembershipStatus.REMOVED.value
            membership.ends_at = utc_now()
            membership.cancel_at_period_end = False
            membership.removal_reason = reason[:500]
            membership.version += 1
            await self._record_change(
                session,
                membership,
                action="MEMBERSHIP_REMOVED",
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                before=before,
                reason=reason,
            )
            await self._cancel_jobs(session, membership.id)
            await session.commit()
            return self._snapshot(membership)

    async def sync_manual_role(
        self,
        guild_id: int,
        user_id: int,
        *,
        has_role: bool,
        actor_user_id: int,
    ) -> MembershipSnapshot | None:
        if has_role:
            return await self._manual_add(guild_id, user_id, actor_user_id)
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            if membership is None or membership.status != MembershipStatus.ACTIVE.value:
                return self._snapshot(membership) if membership is not None else None
            before = self._payload(membership)
            membership.status = MembershipStatus.REMOVED.value
            membership.ends_at = utc_now()
            membership.cancel_at_period_end = False
            membership.removal_reason = "manual_role_removed"
            membership.version += 1
            await self._record_change(
                session,
                membership,
                action="MEMBERSHIP_ROLE_REMOVED",
                actor_user_id=actor_user_id,
                interaction_id=None,
                before=before,
                reason="manual_role_removed",
            )
            await self._cancel_jobs(session, membership.id)
            await session.commit()
            return self._snapshot(membership)

    async def import_role_holder(
        self, guild_id: int, user_id: int, *, actor_user_id: int
    ) -> MembershipSnapshot | None:
        existing = await self.get(guild_id, user_id)
        if existing is not None and existing.is_active:
            return existing
        return await self._manual_add(guild_id, user_id, actor_user_id)

    async def active_user_ids(self, guild_id: int) -> set[int]:
        now = utc_now()
        async with self.database.session() as session:
            rows = (
                await session.scalars(
                    select(Membership.user_id).where(
                        Membership.guild_id == guild_id,
                        Membership.status == MembershipStatus.ACTIVE.value,
                        (Membership.ends_at.is_(None) | (Membership.ends_at > now)),
                    )
                )
            ).all()
            return set(rows)

    async def process_due(self, guild_id: int, *, actor_user_id: int) -> list[int]:
        now = utc_now()
        expired_users: list[int] = []
        async with self.database.session() as session:
            jobs = (
                await session.scalars(
                    select(ScheduledJob)
                    .where(
                        ScheduledJob.guild_id == guild_id,
                        ScheduledJob.job_type == "MEMBERSHIP_EXPIRE",
                        ScheduledJob.status == JobStatus.PENDING.value,
                        ScheduledJob.run_at <= now,
                    )
                    .order_by(ScheduledJob.run_at, ScheduledJob.id)
                    .with_for_update(skip_locked=True)
                    .limit(100)
                )
            ).all()
            for job in jobs:
                job.status = JobStatus.RUNNING.value
                job.locked_at = now
                job.locked_by = "axis-bot"
                job.attempts += 1
                try:
                    membership_id = uuid.UUID(str(job.payload.get("membership_id")))
                except (ValueError, TypeError, AttributeError):
                    job.status = JobStatus.FAILED.value
                    job.last_error = "INVALID_MEMBERSHIP_ID"
                    continue
                membership = await session.scalar(
                    select(Membership)
                    .where(Membership.id == membership_id)
                    .with_for_update()
                )
                if (
                    membership is None
                    or membership.guild_id != guild_id
                    or membership.status != MembershipStatus.ACTIVE.value
                    or membership.ends_at is None
                    or _aware(membership.ends_at) > now
                ):
                    job.status = JobStatus.CANCELLED.value
                    continue
                before = self._payload(membership)
                membership.status = MembershipStatus.EXPIRED.value
                membership.cancel_at_period_end = False
                membership.version += 1
                await self._record_change(
                    session,
                    membership,
                    action="MEMBERSHIP_EXPIRED",
                    actor_user_id=actor_user_id,
                    interaction_id=None,
                    before=before,
                    reason="scheduled_expiry",
                )
                job.status = JobStatus.SUCCEEDED.value
                expired_users.append(membership.user_id)
            await session.commit()
        return expired_users

    async def _manual_add(
        self, guild_id: int, user_id: int, actor_user_id: int
    ) -> MembershipSnapshot:
        async with self.database.session() as session:
            membership = await self._locked(session, guild_id, user_id)
            before = self._payload(membership) if membership is not None else None
            if membership is None:
                membership = Membership(
                    guild_id=guild_id,
                    user_id=user_id,
                    status=MembershipStatus.ACTIVE.value,
                    source=MembershipSource.MANUAL.value,
                    starts_at=utc_now(),
                    ends_at=None,
                    created_by=actor_user_id,
                )
                session.add(membership)
            else:
                membership.status = MembershipStatus.ACTIVE.value
                membership.source = MembershipSource.MANUAL.value
                membership.starts_at = utc_now()
                membership.ends_at = None
                membership.cancel_at_period_end = False
                membership.removal_reason = None
                membership.version += 1
            await session.flush()
            await self._record_change(
                session,
                membership,
                action="MEMBERSHIP_ROLE_ADDED",
                actor_user_id=actor_user_id,
                interaction_id=None,
                before=before,
                reason="manual_role_added",
            )
            await self._cancel_jobs(session, membership.id)
            await session.commit()
            return self._snapshot(membership)

    @staticmethod
    async def _locked(
        session: AsyncSession, guild_id: int, user_id: int
    ) -> Membership | None:
        return await session.scalar(
            select(Membership)
            .where(Membership.guild_id == guild_id, Membership.user_id == user_id)
            .with_for_update()
        )

    @staticmethod
    def _validate_user_and_days(user_id: int, days: int | None) -> None:
        if user_id <= 0:
            raise MembershipValidationError("USER_ID_INVALID")
        if days is not None and not 1 <= days <= 3650:
            raise MembershipValidationError("DURATION_INVALID")

    @staticmethod
    def _payload(membership: Membership | None) -> dict[str, object] | None:
        if membership is None:
            return None
        return {
            "status": membership.status,
            "source": membership.source,
            "starts_at": membership.starts_at.isoformat(),
            "ends_at": membership.ends_at.isoformat() if membership.ends_at else None,
            "cancel_at_period_end": membership.cancel_at_period_end,
            "version": membership.version,
        }

    @classmethod
    async def _record_change(
        cls,
        session: AsyncSession,
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
    async def _cancel_jobs(session: AsyncSession, membership_id: uuid.UUID) -> None:
        jobs = (
            await session.scalars(
                select(ScheduledJob).where(
                    ScheduledJob.dedupe_key.like(f"membership-expiry:{membership_id}:%"),
                    ScheduledJob.status.in_(
                        [JobStatus.PENDING.value, JobStatus.RUNNING.value]
                    ),
                )
            )
        ).all()
        for job in jobs:
            job.status = JobStatus.CANCELLED.value

    @classmethod
    async def _reschedule(
        cls, session: AsyncSession, membership: Membership
    ) -> None:
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
                payload={
                    "membership_id": str(membership.id),
                    "user_id": membership.user_id,
                },
            )
        )

    @staticmethod
    def _snapshot(membership: Membership) -> MembershipSnapshot:
        return MembershipSnapshot(
            id=membership.id,
            guild_id=membership.guild_id,
            user_id=membership.user_id,
            status=membership.status,
            source=membership.source,
            starts_at=membership.starts_at,
            ends_at=membership.ends_at,
            cancel_at_period_end=membership.cancel_at_period_end,
            version=membership.version,
        )
