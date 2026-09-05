from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.base import Base
from app.db.models import (
    AccessApplication,
    GuildConfig,
    MembershipEntitlement,
    MembershipTrial,
    NewcomerProfile,
)
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


async def approve_application(
    database: Database,
    acknowledgements: MembershipAcknowledgementService,
    user_id: int,
) -> AccessApplication:
    now = datetime(2026, 8, 31, 12, tzinfo=UTC)
    await acknowledgements.accept_risk(GUILD_ID, user_id, interaction_id=900)
    async with database.session() as session:
        profile = NewcomerProfile(
            guild_id=GUILD_ID,
            discord_user_id=user_id,
            discord_username_snapshot="approved_user",
            discord_display_name_snapshot="Approved User",
            first_joined_at=now,
            last_joined_at=now,
            join_count=1,
            approved_at=now,
        )
        application = AccessApplication(
            guild_id=GUILD_ID,
            discord_user_id=user_id,
            discord_username_snapshot="approved_user",
            discord_display_name_snapshot="Approved User",
            discovery_source="DISCORD",
            interests=["SWING"],
            risk_acknowledged=True,
            community_rules_acknowledged=True,
            status="APPROVED",
            submitted_at=now,
            reviewed_at=now,
            reviewed_by_user_id=99,
        )
        session.add_all([profile, application])
        await session.commit()
        session.expunge(application)
        return application


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
        with pytest.raises(MembershipAccessError, match="ACCESS_APPROVAL_REQUIRED"):
            await access.claim_free_trial(GUILD_ID, USER_ID, interaction_id=4, now=claimed_at)
        application = await approve_application(database, acknowledgements, USER_ID)
        trial = await access.claim_free_trial(
            GUILD_ID,
            USER_ID,
            interaction_id=4,
            application_id=application.id,
            approved_by_user_id=99,
            now=claimed_at,
        )
        window = access.calendar.trading_window(claimed_at, 3)
        assert trial.starts_at == claimed_at
        assert trial.ends_at == window.expires_at
        assert trial.first_trading_day == window.first_trading_day
        assert trial.last_trading_day == window.last_trading_day
        assert await access.should_have_access(GUILD_ID, USER_ID)
        with pytest.raises(MembershipAccessError, match="FREE_TRIAL_ALREADY_CLAIMED"):
            await access.claim_free_trial(
                GUILD_ID,
                USER_ID,
                interaction_id=5,
                application_id=application.id,
                approved_by_user_id=99,
                now=claimed_at,
            )
        async with database.session() as session:
            stored = await session.scalar(select(MembershipTrial))
        assert stored is not None
        assert stored.duration_unit == "TRADING_DAY"
        assert stored.duration_amount == 3
        assert stored.calendar_days_granted is None
        assert stored.trading_days_granted == 3
        assert stored.first_trading_day == window.first_trading_day
        assert stored.last_trading_day == window.last_trading_day
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_free_trial_skips_weekends_and_holidays_with_trading_calendar() -> None:
    database, acknowledgements, access = await services()
    claims = (
        (USER_ID + 1, datetime(2026, 9, 5, 14, tzinfo=UTC)),  # Saturday
        (USER_ID + 2, datetime(2026, 9, 7, 14, tzinfo=UTC)),  # U.S. Labor Day
    )
    try:
        for index, (user_id, claimed_at) in enumerate(claims, start=10):
            application = await approve_application(database, acknowledgements, user_id)
            trial = await access.claim_free_trial(
                GUILD_ID,
                user_id,
                interaction_id=index + 100,
                application_id=application.id,
                approved_by_user_id=99,
                now=claimed_at,
            )
            window = access.calendar.trading_window(claimed_at, 3)
            assert trial.ends_at == window.expires_at
            assert trial.first_trading_day == window.first_trading_day
            assert trial.last_trading_day == window.last_trading_day
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approval_auto_trial_is_created_even_when_other_access_is_active() -> None:
    database, acknowledgements, access = await services()
    user_id = USER_ID + 3
    try:
        application = await approve_application(database, acknowledgements, user_id)
        await access.grant(
            GUILD_ID,
            user_id,
            days=None,
            actor_user_id=99,
            interaction_id=21,
        )
        assert await access.free_trial_claim_state(GUILD_ID, user_id) == "ACCESS_ACTIVE"
        await access.claim_free_trial(
            GUILD_ID,
            user_id,
            interaction_id=22,
            application_id=application.id,
            approved_by_user_id=99,
        )
        async with database.session() as session:
            stored = await session.scalar(
                select(MembershipTrial).where(MembershipTrial.discord_user_id == user_id)
            )
        assert stored is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_extensions_are_separate_and_cross_weekend_and_holiday() -> None:
    database, _, access = await services()
    christmas_eve_expiry = datetime(2026, 12, 25, 4, 59, 59, tzinfo=UTC)
    try:
        async with database.session() as session:
            source = MembershipEntitlement(
                guild_id=GUILD_ID,
                discord_user_id=USER_ID,
                entitlement_type=EntitlementType.DAY_PASS.value,
                status=EntitlementStatus.ACTIVE.value,
                starts_at=datetime(2026, 12, 24, 14, tzinfo=UTC),
                ends_at=christmas_eve_expiry,
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
            now=datetime(2026, 12, 24, 20, tzinfo=UTC),
        )
        assert extension.id != source_id
        assert extension.first_trading_day.isoformat() == "2026-12-28"
        assert extension.last_trading_day.isoformat() == "2026-12-30"
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
