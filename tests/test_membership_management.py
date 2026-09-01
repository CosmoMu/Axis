from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, MembershipEntitlement, utc_now
from app.db.session import Database
from app.domain.enums import EntitlementStatus, MembershipExtensionType
from app.services.membership_access import (
    MembershipAccessService,
    MembershipAcknowledgementService,
)
from app.services.membership_management import MembershipManagementService
from app.services.trading_calendar import TradingCalendarService

GUILD_ID = 1543309921066684567


@pytest.mark.asyncio
async def test_manager_actions_create_independent_entitlements_and_sync_manual_role() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    access = MembershipAccessService(
        database,
        TradingCalendarService(),
        MembershipAcknowledgementService(database),
    )
    service = MembershipManagementService(database, access)
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
        assert granted.is_active and granted.entitlement_count == 1

        extended = await service.extend_access(
            GUILD_ID,
            granted.user_id,
            extension_type=MembershipExtensionType.TRADING_DAYS.value,
            amount=3,
            actor_user_id=101,
            interaction_id=202,
        )
        assert extended.entitlement_count == 2
        assert "MANUAL_EXTENSION" in extended.source

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
        assert removed.status == EntitlementStatus.REVOKED.value
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
        assert manual_removed.status == EntitlementStatus.REVOKED.value

        expiring = await service.grant(
            GUILD_ID,
            100000000000000003,
            days=7,
            actor_user_id=101,
            interaction_id=205,
        )
        async with database.session() as session:
            entitlement = await session.scalar(
                select(MembershipEntitlement).where(MembershipEntitlement.id == expiring.id)
            )
            assert entitlement is not None
            entitlement.ends_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        expired_users = await service.process_due(GUILD_ID, actor_user_id=999)
        expired = await service.get(GUILD_ID, expiring.user_id)
        assert expired_users == [expiring.user_id]
        assert expired is not None and expired.status == EntitlementStatus.EXPIRED.value
        imported = await service.import_role_holder(
            GUILD_ID,
            expiring.user_id,
            actor_user_id=999,
        )
        assert imported is not None and imported.status == EntitlementStatus.EXPIRED.value

        async with database.session() as session:
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
            entitlement_count = await session.scalar(
                select(func.count()).select_from(MembershipEntitlement)
            )
        assert audit_count == 10
        assert entitlement_count == 4
    finally:
        await database.dispose()
