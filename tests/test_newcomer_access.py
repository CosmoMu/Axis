from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import (
    AccessApplication,
    GuildConfig,
    MembershipEntitlement,
    MembershipTrial,
    NewcomerRiskFlag,
)
from app.db.session import Database
from app.domain.enums import EntitlementStatus, EntitlementType
from app.services.membership_access import (
    MembershipAccessError,
    MembershipAccessService,
    MembershipAcknowledgementService,
)
from app.services.newcomer_access import (
    NewcomerAccessError,
    NewcomerAccessService,
    NewcomerRiskScanner,
)
from app.services.trading_calendar import TradingCalendarService

GUILD_ID = 1543309921066684567
USER_ID = 900000000000000001
MANAGER_ID = 900000000000000099


async def setup_services() -> tuple[
    Database,
    NewcomerAccessService,
    NewcomerRiskScanner,
    MembershipAccessService,
]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        await session.commit()
    acknowledgements = MembershipAcknowledgementService(database)
    newcomer = NewcomerAccessService(database, acknowledgements)
    scanner = NewcomerRiskScanner(
        database,
        ("AXIS", "AXIS BOT", "AXIS ADMIN", "AXIS SUPPORT", "VALE"),
    )
    access = MembershipAccessService(
        database,
        TradingCalendarService(),
        acknowledgements,
    )
    return database, newcomer, scanner, access


async def submit(
    service: NewcomerAccessService,
    user_id: int = USER_ID,
) -> AccessApplication:
    await service.register_join(
        GUILD_ID,
        user_id,
        username="axis_user",
        display_name="Axis User",
        joined_at=datetime(2026, 8, 31, 15, tzinfo=UTC),
    )
    snapshot = await service.submit_application(
        GUILD_ID,
        user_id,
        username="axis_user",
        display_name="Axis User",
        discovery_source="FRIEND_REFERRAL",
        referred_by="friend_name",
        interests=("SHORT_TERM", "SWING"),
        interaction_id=101,
    )
    async with service.database.session() as session:
        row = await session.get(AccessApplication, snapshot.id)
        assert row is not None
        session.expunge(row)
        return row


@pytest.mark.asyncio
async def test_application_persists_answers_and_blocks_duplicates() -> None:
    database, newcomer, _, _ = await setup_services()
    try:
        application = await submit(newcomer)
        assert application.status == "PENDING"
        assert application.discovery_source == "FRIEND_REFERRAL"
        assert application.referred_by_text == "friend_name"
        assert application.interests == ["SHORT_TERM", "SWING"]
        assert application.risk_acknowledged is True
        assert application.community_rules_acknowledged is True
        with pytest.raises(NewcomerAccessError, match="APPLICATION_ALREADY_PENDING"):
            await newcomer.submit_application(
                GUILD_ID,
                USER_ID,
                username="axis_user",
                display_name="Axis User",
                discovery_source="DISCORD",
                referred_by=None,
                interests=("LEAPS",),
                interaction_id=102,
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_production_baseline_approves_existing_user_without_consuming_trial() -> None:
    database, newcomer, _, access = await setup_services()
    try:
        changed = await newcomer.baseline_approved_user(
            GUILD_ID,
            USER_ID,
            username="existing_user",
            display_name="Existing User",
            joined_at=datetime(2026, 8, 1, tzinfo=UTC),
            actor_user_id=MANAGER_ID,
        )
        activated = await newcomer.activate_gate(GUILD_ID, actor_user_id=MANAGER_ID)
        assert changed is True
        assert await newcomer.is_approved(GUILD_ID, USER_ID)
        assert await newcomer.gate_activated_at(GUILD_ID) == activated
        assert await access.free_trial_claim_state(GUILD_ID, USER_ID) == "ELIGIBLE"
        async with database.session() as session:
            trial_count = await session.scalar(select(func.count()).select_from(MembershipTrial))
        assert trial_count == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approve_starts_exact_calendar_trial_once_and_approval_survives_expiry() -> None:
    database, newcomer, scanner, access = await setup_services()
    approved_at = datetime(2026, 8, 20, 23, 30, tzinfo=UTC)
    try:
        application = await submit(newcomer)
        flagged = await newcomer.review(
            application.id,
            action="FLAGGED",
            actor_user_id=MANAGER_ID,
            interaction_id=201,
        )
        assert flagged.status == "FLAGGED"
        approved = await newcomer.review(
            application.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=202,
        )
        trial = await access.claim_free_trial(
            GUILD_ID,
            USER_ID,
            interaction_id=202,
            application_id=approved.id,
            approved_by_user_id=MANAGER_ID,
            now=approved_at,
        )
        window = access.calendar.trading_window(approved_at, 3)
        assert trial.ends_at == window.expires_at
        assert trial.first_trading_day == window.first_trading_day
        assert trial.last_trading_day == window.last_trading_day
        with pytest.raises(MembershipAccessError, match="FREE_TRIAL_ALREADY_CLAIMED"):
            await access.claim_free_trial(
                GUILD_ID,
                USER_ID,
                interaction_id=203,
                application_id=approved.id,
                approved_by_user_id=MANAGER_ID,
                now=approved_at,
            )
        assert await newcomer.is_approved(GUILD_ID, USER_ID)
        expired = await access.expire_due(GUILD_ID, actor_user_id=MANAGER_ID)
        assert expired == [USER_ID]
        assert not await access.should_have_access(GUILD_ID, USER_ID)
        assert await newcomer.is_approved(GUILD_ID, USER_ID)
        async with database.session() as session:
            trial_row = await session.scalar(select(MembershipTrial))
        assert trial_row is not None
        assert trial_row.application_id == approved.id
        assert trial_row.approved_by_user_id == MANAGER_ID
        assert trial_row.status == "EXPIRED"
        risk = await scanner.scan(
            GUILD_ID,
            USER_ID,
            username="axis_user",
            display_name="Axis User",
            account_created_at=approved_at - timedelta(days=365),
            application_id=approved.id,
            now=approved_at,
        )
        assert "TRIAL_ALREADY_USED" in {flag.risk_code for flag in risk.flags}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approved_application_without_trial_is_recoverable_after_restart() -> None:
    database, newcomer, _, access = await setup_services()
    try:
        application = await submit(newcomer)
        approved = await newcomer.review(
            application.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=250,
        )
        pending = await newcomer.approved_applications_without_trial(GUILD_ID)
        assert [item.id for item in pending] == [approved.id]

        await access.claim_free_trial(
            GUILD_ID,
            USER_ID,
            interaction_id=None,
            application_id=approved.id,
            approved_by_user_id=MANAGER_ID,
        )
        assert await newcomer.approved_applications_without_trial(GUILD_ID) == ()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approved_member_welcomes_are_persisted_per_destination() -> None:
    database, newcomer, _, _ = await setup_services()
    try:
        application = await submit(newcomer)
        approved = await newcomer.review(
            application.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=260,
        )
        pending = await newcomer.approved_applications_pending_welcome(GUILD_ID)
        assert [item.id for item in pending] == [approved.id]

        assert await newcomer.attach_approval_welcome_message(
            approved.id,
            destination="LOBBY",
            message_id=701,
            actor_user_id=MANAGER_ID,
        )
        assert not await newcomer.attach_approval_welcome_message(
            approved.id,
            destination="LOBBY",
            message_id=702,
            actor_user_id=MANAGER_ID,
        )
        partially_sent = await newcomer.get_application(approved.id)
        assert partially_sent is not None
        assert partially_sent.lobby_welcome_message_id == 701
        assert partially_sent.member_lounge_welcome_message_id is None

        assert await newcomer.attach_approval_welcome_message(
            approved.id,
            destination="MEMBER_LOUNGE",
            message_id=703,
            actor_user_id=MANAGER_ID,
        )
        assert await newcomer.approved_applications_pending_welcome(GUILD_ID) == ()
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_trial_requires_approved_application_and_uses_trading_calendar() -> None:
    database, newcomer, _, access = await setup_services()
    try:
        application = await submit(newcomer)
        with pytest.raises(MembershipAccessError, match="ACCESS_APPROVAL_REQUIRED"):
            await access.claim_free_trial(
                GUILD_ID,
                USER_ID,
                interaction_id=301,
                application_id=application.id,
                approved_by_user_id=MANAGER_ID,
            )
        approved = await newcomer.review(
            application.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=302,
        )
        saturday = datetime(2026, 9, 5, 14, tzinfo=UTC)
        trial = await access.claim_free_trial(
            GUILD_ID,
            USER_ID,
            interaction_id=302,
            application_id=approved.id,
            approved_by_user_id=MANAGER_ID,
            now=saturday,
        )
        assert trial.first_trading_day.isoformat() == "2026-09-08"
        assert trial.last_trading_day.isoformat() == "2026-09-10"
        assert trial.ends_at == datetime(2026, 9, 11, 3, 59, 59, tzinfo=UTC)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rejoin_rules_distinguish_approved_rejected_and_never_approved() -> None:
    database, newcomer, _, _ = await setup_services()
    try:
        approved_app = await submit(newcomer, USER_ID)
        await newcomer.review(
            approved_app.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=401,
        )
        approved_rejoin = await newcomer.register_join(
            GUILD_ID,
            USER_ID,
            username="renamed_user",
            display_name="Renamed User",
        )
        assert approved_rejoin.approved is True
        assert await newcomer.application_state(GUILD_ID, USER_ID) == "APPROVED"

        rejected_id = USER_ID + 1
        rejected_app = await submit(newcomer, rejected_id)
        await newcomer.review(
            rejected_app.id,
            action="REJECTED",
            actor_user_id=MANAGER_ID,
            interaction_id=402,
        )
        rejected_rejoin = await newcomer.register_join(
            GUILD_ID,
            rejected_id,
            username="rejected",
            display_name="Rejected",
        )
        assert rejected_rejoin.approved is False
        assert await newcomer.application_state(GUILD_ID, rejected_id) == "REJECTED"

        new_id = USER_ID + 2
        first = await newcomer.register_join(
            GUILD_ID,
            new_id,
            username="new_user",
            display_name="New User",
        )
        second = await newcomer.register_join(
            GUILD_ID,
            new_id,
            username="new_user",
            display_name="New User",
        )
        assert first.approved is False
        assert second.approved is False
        assert second.join_count == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_approved_renamed_rejoin_keeps_trial_history_and_active_monthly_access() -> None:
    database, newcomer, _, access = await setup_services()
    try:
        application = await submit(newcomer)
        approved = await newcomer.review(
            application.id,
            action="APPROVED",
            actor_user_id=MANAGER_ID,
            interaction_id=450,
        )
        await access.claim_free_trial(
            GUILD_ID,
            USER_ID,
            interaction_id=450,
            application_id=approved.id,
            approved_by_user_id=MANAGER_ID,
            now=datetime(2026, 8, 1, tzinfo=UTC),
        )
        await access.expire_due(GUILD_ID, actor_user_id=MANAGER_ID)
        rejoined = await newcomer.register_join(
            GUILD_ID,
            USER_ID,
            username="renamed_after_trial",
            display_name="Renamed After Trial",
        )
        assert rejoined.approved is True
        assert await newcomer.has_trial_history(USER_ID) is True
        with pytest.raises(MembershipAccessError, match="FREE_TRIAL_ALREADY_CLAIMED"):
            await access.claim_free_trial(
                GUILD_ID,
                USER_ID,
                interaction_id=451,
                application_id=approved.id,
                approved_by_user_id=MANAGER_ID,
            )

        now = datetime.now(UTC)
        async with database.session() as session:
            session.add(
                MembershipEntitlement(
                    guild_id=GUILD_ID,
                    discord_user_id=USER_ID,
                    entitlement_type=EntitlementType.MONTHLY.value,
                    status=EntitlementStatus.ACTIVE.value,
                    starts_at=now,
                    ends_at=now + timedelta(days=30),
                )
            )
            await session.commit()
        assert await access.should_have_access(GUILD_ID, USER_ID) is True
        assert (await newcomer.profile(GUILD_ID, USER_ID)).approved is True
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_risk_scanner_rules_are_persistent_deduplicated_and_non_decisive() -> None:
    database, newcomer, scanner, _ = await setup_services()
    try:
        application = await submit(newcomer)
        await newcomer.review(
            application.id,
            action="FLAGGED",
            actor_user_id=MANAGER_ID,
            interaction_id=500,
        )
        await newcomer.review(
            application.id,
            action="REJECTED",
            actor_user_id=MANAGER_ID,
            interaction_id=501,
        )
        await newcomer.register_join(
            GUILD_ID,
            USER_ID,
            username="AXlS_SUPPORT",
            display_name="V4LE",
        )
        now = datetime(2026, 8, 31, 20, tzinfo=UTC)
        first = await scanner.scan(
            GUILD_ID,
            USER_ID,
            username="AXlS_SUPPORT",
            display_name="V4LE",
            account_created_at=now - timedelta(days=2),
            application_id=application.id,
            now=now,
        )
        codes = {flag.risk_code for flag in first.flags}
        assert {
            "VERY_NEW_ACCOUNT",
            "PREVIOUS_REJECTION",
            "PREVIOUS_FLAG",
            "REJOIN_WITHOUT_APPROVAL",
            "POSSIBLE_IMPERSONATION",
        } <= codes
        assert scanner.protected_identity_match("AXlS_SUPPORT") == "AXIS SUPPORT"
        assert scanner.protected_identity_match("V4LE") == "VALE"
        second = await scanner.scan(
            GUILD_ID,
            USER_ID,
            username="AXlS_SUPPORT",
            display_name="V4LE",
            account_created_at=now - timedelta(days=2),
            application_id=application.id,
            now=now + timedelta(hours=1),
        )
        assert not second.created_codes
        async with database.session() as session:
            count = await session.scalar(select(func.count()).select_from(NewcomerRiskFlag))
            stored = (
                await session.scalars(
                    select(NewcomerRiskFlag).where(
                        NewcomerRiskFlag.risk_code == "POSSIBLE_IMPERSONATION"
                    )
                )
            ).one()
        assert count == len(first.flags)
        assert stored.occurrence_count == 2
        assert await newcomer.application_state(GUILD_ID, USER_ID) == "REJECTED"
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_security_metrics_expose_aggregate_health_without_usernames() -> None:
    database, newcomer, scanner, _ = await setup_services()
    try:
        await submit(newcomer)
        now = datetime(2026, 8, 31, 20, tzinfo=UTC)
        await scanner.scan(
            GUILD_ID,
            USER_ID,
            username="AXIS ADMIN",
            display_name="AXIS ADMIN",
            account_created_at=now - timedelta(days=1),
            now=now,
        )
        metrics = await newcomer.metrics(GUILD_ID, now=now)
        assert metrics.newcomers == 1
        assert metrics.pending_applications == 1
        assert metrics.high_risk_newcomers == 1
        assert metrics.health == "ATTENTION"
    finally:
        await database.dispose()
