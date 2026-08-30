from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.models import GuildConfig, MembershipEntitlement, MembershipTrial
from app.db.session import Database
from app.domain.enums import EntitlementStatus, EntitlementType, MembershipExtensionType
from app.services.membership_access import (
    MembershipAccessError,
    MembershipAccessService,
    MembershipAcknowledgementService,
)
from app.services.trading_calendar import TradingCalendarService

GUILD_ID = 1543309921066684567
USER_ID = 100000000000000001


async def services() -> tuple[
    Database,
    MembershipAcknowledgementService,
    MembershipAccessService,
]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()
    acknowledgements = MembershipAcknowledgementService(database)
    access = MembershipAccessService(
        database,
        TradingCalendarService(),
        acknowledgements,
    )
    return database, acknowledgements, access


def test_trading_calendar_handles_close_weekend_and_formal_holiday() -> None:
    calendar = TradingCalendarService()
    before_close = calendar.trading_window(datetime(2026, 9, 4, 14, tzinfo=UTC), 3)
    after_close = calendar.trading_window(datetime(2026, 9, 4, 22, tzinfo=UTC), 1)
    weekend = calendar.trading_window(datetime(2026, 9, 5, 14, tzinfo=UTC), 1)

    assert str(before_close.first_trading_day) == "2026-09-04"
    assert str(before_close.last_trading_day) == "2026-09-09"
    assert str(after_close.first_trading_day) == "2026-09-08"
    assert weekend == after_close
    assert after_close.expires_at.astimezone().tzinfo is not None


@pytest.mark.asyncio
async def test_free_trial_requires_versioned_ack_and_is_lifetime_once() -> None:
    database, acknowledgements, access = await services()
    claimed_at = datetime(2026, 9, 4, 14, tzinfo=UTC)
    try:
        with pytest.raises(MembershipAccessError, match="RISK_ACKNOWLEDGEMENT_REQUIRED"):
            await access.claim_free_trial(GUILD_ID, USER_ID, interaction_id=1, now=claimed_at)
        assert await acknowledgements.accept_risk(GUILD_ID, USER_ID, interaction_id=2)
        assert not await acknowledgements.accept_risk(GUILD_ID, USER_ID, interaction_id=3)
        trial = await access.claim_free_trial(GUILD_ID, USER_ID, interaction_id=4, now=claimed_at)
        assert trial.first_trading_day.isoformat() == "2026-09-04"
        assert trial.last_trading_day.isoformat() == "2026-09-09"
        assert await access.should_have_access(GUILD_ID, USER_ID)
        with pytest.raises(MembershipAccessError, match="FREE_TRIAL_ALREADY_CLAIMED"):
            await access.claim_free_trial(GUILD_ID, USER_ID, interaction_id=5, now=claimed_at)
        async with database.session() as session:
            stored = await session.scalar(select(MembershipTrial))
        assert stored is not None and stored.trading_days_granted == 3
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_extensions_are_separate_and_cross_weekend_and_holiday() -> None:
    database, _, access = await services()
    friday_expiry = datetime(2026, 9, 5, 3, 59, 59, tzinfo=UTC)
    try:
        async with database.session() as session:
            source = MembershipEntitlement(
                guild_id=GUILD_ID,
                discord_user_id=USER_ID,
                entitlement_type=EntitlementType.DAY_PASS.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=datetime(2026, 9, 4, 14, tzinfo=UTC),
                ends_at=friday_expiry,
            )
            session.add(source)
            await session.commit()
            source_id = source.id
        extension = await access.extend(
            GUILD_ID,
            USER_ID,
            extension_type=MembershipExtensionType.TRADING_DAYS.value,
            amount=3,
            actor_user_id=99,
            interaction_id=100,
            now=datetime(2026, 9, 4, 20, tzinfo=UTC),
        )
        assert extension.id != source_id
        assert extension.first_trading_day.isoformat() == "2026-09-08"
        assert extension.last_trading_day.isoformat() == "2026-09-10"
        status = await access.status(GUILD_ID, USER_ID)
        assert len(status.entitlements) == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_expired_member_extension_activates_immediately_and_multiple_access_survives() -> (
    None
):
    database, _, access = await services()
    saturday = datetime(2026, 9, 5, 14, tzinfo=UTC)
    try:
        extension = await access.extend(
            GUILD_ID,
            USER_ID,
            extension_type=MembershipExtensionType.TRADING_DAYS.value,
            amount=3,
            actor_user_id=99,
            interaction_id=100,
            now=saturday,
        )
        assert extension.first_trading_day.isoformat() == "2026-09-08"
        assert extension.last_trading_day.isoformat() == "2026-09-10"
        assert extension.is_active

        await access.grant(
            GUILD_ID,
            USER_ID,
            days=30,
            actor_user_id=99,
            interaction_id=101,
        )
        async with database.session() as session:
            stored_extension = await session.get(MembershipEntitlement, extension.id)
            assert stored_extension is not None
            stored_extension.status = EntitlementStatus.EXPIRED.value
            stored_extension.ends_at = saturday - timedelta(seconds=1)
            await session.commit()
        assert await access.should_have_access(GUILD_ID, USER_ID)
        assert await access.count_active(GUILD_ID, USER_ID) == 1
    finally:
        await database.dispose()
