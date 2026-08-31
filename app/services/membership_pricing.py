from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from app.db.models import AuditLog, MembershipPrice
from app.db.session import Database
from app.domain.enums import MembershipPlanType


class MembershipPricingError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class MembershipPriceVersion:
    environment: str
    plan_type: str
    pricing_version: str
    unit_amount: int
    currency: str
    billing_interval: str | None
    stripe_product_id: str | None
    stripe_price_id: str | None
    is_current: bool
    is_active: bool


class MembershipPricingService:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_versions(self, environment: str) -> tuple[MembershipPriceVersion, ...]:
        normalized = _environment(environment)
        async with self.database.session() as session:
            rows = list(
                await session.scalars(
                    select(MembershipPrice)
                    .where(MembershipPrice.environment == normalized)
                    .order_by(MembershipPrice.plan_type, MembershipPrice.created_at)
                )
            )
        return tuple(_snapshot(item) for item in rows)

    async def create_version(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        environment: str,
        plan_type: str,
        pricing_version: str,
        unit_amount: int,
        currency: str,
        stripe_product_id: str,
        stripe_price_id: str,
        make_current: bool,
    ) -> MembershipPriceVersion:
        normalized_environment = _environment(environment)
        normalized_plan = _plan(plan_type)
        normalized_version = pricing_version.strip().upper()
        normalized_currency = currency.strip().lower()
        if not normalized_version or len(normalized_version) > 40:
            raise MembershipPricingError("PRICING_VERSION_INVALID")
        if unit_amount <= 0:
            raise MembershipPricingError("UNIT_AMOUNT_INVALID")
        if len(normalized_currency) != 3:
            raise MembershipPricingError("CURRENCY_INVALID")
        if not stripe_product_id.startswith("prod_") or not stripe_price_id.startswith("price_"):
            raise MembershipPricingError("STRIPE_PRICE_MAPPING_INVALID")
        async with self.database.session() as session:
            existing = await session.scalar(
                select(MembershipPrice).where(
                    MembershipPrice.environment == normalized_environment,
                    MembershipPrice.plan_type == normalized_plan,
                    MembershipPrice.pricing_version == normalized_version,
                )
            )
            if existing is not None:
                raise MembershipPricingError("PRICING_VERSION_ALREADY_EXISTS")
            before = None
            if make_current:
                current = list(
                    await session.scalars(
                        select(MembershipPrice)
                        .where(
                            MembershipPrice.environment == normalized_environment,
                            MembershipPrice.plan_type == normalized_plan,
                            MembershipPrice.is_current.is_(True),
                        )
                        .with_for_update()
                    )
                )
                before = [item.pricing_version for item in current]
                for item in current:
                    item.is_current = False
            row = MembershipPrice(
                environment=normalized_environment,
                plan_type=normalized_plan,
                pricing_version=normalized_version,
                stripe_product_id=stripe_product_id,
                stripe_price_id=stripe_price_id,
                unit_amount=unit_amount,
                currency=normalized_currency,
                billing_interval=(
                    "month" if normalized_plan == MembershipPlanType.MONTHLY.value else None
                ),
                is_current=make_current,
                is_active=True,
            )
            session.add(row)
            await session.flush()
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type="MEMBERSHIP_PRICE_VERSION_CREATED",
                    entity_type="membership_price",
                    entity_id=str(row.id),
                    before_json={"current_versions": before} if before is not None else None,
                    after_json={
                        "environment": normalized_environment,
                        "plan_type": normalized_plan,
                        "pricing_version": normalized_version,
                        "unit_amount": unit_amount,
                        "currency": normalized_currency,
                        "is_current": make_current,
                    },
                )
            )
            await session.commit()
            return _snapshot(row)

    async def switch_current(
        self,
        *,
        guild_id: int,
        actor_user_id: int,
        environment: str,
        plan_type: str,
        pricing_version: str,
    ) -> MembershipPriceVersion:
        normalized_environment = _environment(environment)
        normalized_plan = _plan(plan_type)
        normalized_version = pricing_version.strip().upper()
        async with self.database.session() as session:
            rows = list(
                await session.scalars(
                    select(MembershipPrice)
                    .where(
                        MembershipPrice.environment == normalized_environment,
                        MembershipPrice.plan_type == normalized_plan,
                    )
                    .with_for_update()
                )
            )
            target = next(
                (item for item in rows if item.pricing_version == normalized_version), None
            )
            if target is None or not target.is_active or not target.stripe_price_id:
                raise MembershipPricingError("PRICING_VERSION_NOT_SWITCHABLE")
            previous = [item.pricing_version for item in rows if item.is_current]
            for item in rows:
                item.is_current = item.id == target.id
            session.add(
                AuditLog(
                    guild_id=guild_id,
                    actor_user_id=actor_user_id,
                    action_type="MEMBERSHIP_CURRENT_PRICE_SWITCHED",
                    entity_type="membership_price",
                    entity_id=str(target.id),
                    before_json={"current_versions": previous},
                    after_json={
                        "environment": normalized_environment,
                        "plan_type": normalized_plan,
                        "pricing_version": normalized_version,
                    },
                )
            )
            await session.commit()
            return _snapshot(target)


def _environment(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {"TEST", "LIVE"}:
        raise MembershipPricingError("PAYMENT_ENVIRONMENT_INVALID")
    return normalized


def _plan(value: str) -> str:
    normalized = value.strip().upper()
    if normalized not in {item.value for item in MembershipPlanType}:
        raise MembershipPricingError("MEMBERSHIP_PLAN_INVALID")
    return normalized


def _snapshot(row: MembershipPrice) -> MembershipPriceVersion:
    return MembershipPriceVersion(
        environment=row.environment,
        plan_type=row.plan_type,
        pricing_version=row.pricing_version,
        unit_amount=row.unit_amount,
        currency=row.currency,
        billing_interval=row.billing_interval,
        stripe_product_id=row.stripe_product_id,
        stripe_price_id=row.stripe_price_id,
        is_current=row.is_current,
        is_active=row.is_active,
    )
