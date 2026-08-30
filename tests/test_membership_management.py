from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    AuditLog,
    GuildConfig,
    Membership,
    MembershipEvent,
    ScheduledJob,
    utc_now,
)
from app.db.session import Database
from app.domain.enums import JobStatus, MembershipStatus
from app.services.membership_management import MembershipManagementService

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_membership_lifecycle_scheduling_and_manual_role_sync() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = MembershipManagementService(database)
    try:
        async with database.session() as session:
            session.add(GuildConfig(guild_id=GUILD_ID))
            await session.commit()

        granted = await service.grant(
            GUILD_ID,
            100000000000000001,
            days=30,
            actor_user_id=101,
            interaction_id=201,
        )
        original_end = granted.ends_at
        assert granted.is_active and original_end is not None
        extended = await service.extend(
            GUILD_ID,
            granted.user_id,
            days=7,
            actor_user_id=101,
            interaction_id=202,
        )
        assert extended.ends_at == original_end + timedelta(days=7)
        cancelled = await service.cancel_at_expiry(
            GUILD_ID,
            granted.user_id,
            ends_at=None,
            actor_user_id=101,
            interaction_id=203,
        )
        assert cancelled.cancel_at_period_end is True
        removed = await service.remove(
            GUILD_ID,
            granted.user_id,
            actor_user_id=101,
            interaction_id=204,
        )
        assert removed.status == MembershipStatus.REMOVED.value
        assert granted.user_id not in await service.active_user_ids(GUILD_ID)

        manual = await service.sync_manual_role(
            GUILD_ID,
            100000000000000002,
            has_role=True,
            actor_user_id=101,
        )
        assert manual is not None and manual.ends_at is None and manual.is_active
        manual_removed = await service.sync_manual_role(
            GUILD_ID,
            manual.user_id,
            has_role=False,
            actor_user_id=101,
        )
        assert manual_removed is not None
        assert manual_removed.status == MembershipStatus.REMOVED.value

        expiring = await service.grant(
            GUILD_ID,
            100000000000000003,
            days=7,
            actor_user_id=101,
            interaction_id=205,
        )
        async with database.session() as session:
            membership = await session.get(Membership, expiring.id)
            assert membership is not None
            membership.ends_at = utc_now() - timedelta(seconds=1)
            job = await session.scalar(
                select(ScheduledJob).where(
                    ScheduledJob.dedupe_key.like(f"membership-expiry:{expiring.id}:%"),
                    ScheduledJob.status == JobStatus.PENDING.value,
                )
            )
            assert job is not None
            job.run_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        expired_users = await service.process_due(GUILD_ID, actor_user_id=999)
        expired = await service.get(GUILD_ID, expiring.user_id)
        assert expired_users == [expiring.user_id]
        assert expired is not None and expired.status == MembershipStatus.EXPIRED.value

        async with database.session() as session:
            event_count = await session.scalar(select(func.count()).select_from(MembershipEvent))
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
            succeeded = await session.scalar(
                select(func.count())
                .select_from(ScheduledJob)
                .where(ScheduledJob.status == JobStatus.SUCCEEDED.value)
            )
        assert event_count == audit_count == 8
        assert succeeded == 1
    finally:
        await database.dispose()
