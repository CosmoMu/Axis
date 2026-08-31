from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select

from app.db.base import Base
from app.db.models import AuditLog, GuildConfig, MembershipEntitlement, MembershipPrice
from app.db.session import Database
from app.domain.enums import EntitlementStatus, EntitlementType, MembershipPlanType
from app.services.membership_pricing import MembershipPricingService

GUILD_ID = 1543309921066684567
OWNER_ID = 100000000000000001


async def setup() -> tuple[Database, MembershipPricingService]:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with database.session() as session:
        session.add(GuildConfig(guild_id=GUILD_ID))
        session.add_all(
            [
                MembershipPrice(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000102"),
                    environment="TEST",
                    plan_type=MembershipPlanType.MONTHLY.value,
                    pricing_version="MONTHLY_V1",
                    stripe_product_id="prod_test",
                    stripe_price_id="price_test_v1",
                    unit_amount=9999,
                    currency="usd",
                    billing_interval="month",
                    is_current=True,
                    is_active=True,
                ),
                MembershipPrice(
                    id=uuid.UUID("00000000-0000-4000-8000-000000000202"),
                    environment="LIVE",
                    plan_type=MembershipPlanType.MONTHLY.value,
                    pricing_version="MONTHLY_V1",
                    stripe_product_id="prod_live",
                    stripe_price_id="price_live_v1",
                    unit_amount=9999,
                    currency="usd",
                    billing_interval="month",
                    is_current=True,
                    is_active=True,
                ),
            ]
        )
        await session.commit()
    return database, MembershipPricingService(database)


@pytest.mark.asyncio
async def test_live_price_change_and_rollback_preserve_grandfathered_entitlement() -> None:
    database, service = await setup()
    try:
        async with database.session() as session:
            v1 = await session.scalar(
                select(MembershipPrice).where(
                    MembershipPrice.environment == "LIVE",
                    MembershipPrice.pricing_version == "MONTHLY_V1",
                )
            )
            assert v1 is not None
            session.add(
                MembershipEntitlement(
                    guild_id=GUILD_ID,
                    discord_user_id=OWNER_ID,
                    entitlement_type=EntitlementType.MONTHLY.value,
                    status=EntitlementStatus.ACTIVE.value,
                    starts_at=v1.created_at,
                    membership_price_id=v1.id,
                    pricing_version=v1.pricing_version,
                    stripe_price_id=v1.stripe_price_id,
                    unit_amount_at_signup=v1.unit_amount,
                    currency=v1.currency,
                    provider="stripe",
                    payment_environment="LIVE",
                    provider_subscription_id="sub_live_v1",
                )
            )
            await session.commit()
        v2 = await service.create_version(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            environment="live",
            plan_type="MONTHLY",
            pricing_version="MONTHLY_V2",
            unit_amount=12999,
            currency="usd",
            stripe_product_id="prod_live",
            stripe_price_id="price_live_v2",
            make_current=True,
        )
        assert v2.is_current
        versions = await service.list_versions("LIVE")
        assert {item.pricing_version for item in versions if item.is_current} == {"MONTHLY_V2"}
        await service.switch_current(
            guild_id=GUILD_ID,
            actor_user_id=OWNER_ID,
            environment="LIVE",
            plan_type="MONTHLY",
            pricing_version="MONTHLY_V1",
        )
        versions = await service.list_versions("LIVE")
        assert {item.pricing_version for item in versions if item.is_current} == {"MONTHLY_V1"}
        async with database.session() as session:
            entitlement = await session.scalar(select(MembershipEntitlement))
            audit_count = await session.scalar(select(func.count()).select_from(AuditLog))
        assert entitlement is not None
        assert entitlement.pricing_version == "MONTHLY_V1"
        assert entitlement.unit_amount_at_signup == 9999
        assert audit_count == 2
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_test_and_live_can_use_same_pricing_version_without_id_collision() -> None:
    database, service = await setup()
    try:
        test_versions = await service.list_versions("TEST")
        live_versions = await service.list_versions("LIVE")
        assert test_versions[0].pricing_version == live_versions[0].pricing_version
        assert test_versions[0].stripe_price_id != live_versions[0].stripe_price_id
    finally:
        await database.dispose()
