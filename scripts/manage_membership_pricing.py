#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

import stripe

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.stripe_config import StripeMode  # noqa: E402
from app.services.membership_pricing import MembershipPricingService  # noqa: E402


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


async def _verify_stripe_mapping(
    settings: Settings,
    *,
    environment: str,
    plan: str,
    unit_amount: int,
    currency: str,
    product_id: str,
    price_id: str,
) -> None:
    stripe_config = settings.stripe_config()
    mode = StripeMode.parse(environment)
    selected = stripe_config.live if mode is StripeMode.LIVE else stripe_config.test
    expected_prefix = "sk_live_" if mode is StripeMode.LIVE else "sk_test_"
    if not selected.secret_key.startswith(expected_prefix):
        raise RuntimeError("Selected Stripe environment key is unavailable or mismatched")
    client = stripe.StripeClient(selected.secret_key)
    try:
        product, price = await asyncio.gather(
            asyncio.to_thread(client.v1.products.retrieve, product_id),
            asyncio.to_thread(client.v1.prices.retrieve, price_id),
        )
    except stripe.StripeError as exc:
        raise RuntimeError("Stripe Product/Price verification failed") from exc
    product_data = _plain(product)
    price_data = _plain(price)
    interval = (price_data.get("recurring") or {}).get("interval")
    expected_interval = "month" if plan == "MONTHLY" else None
    if not (
        product_data.get("active")
        and product_data.get("livemode") is mode.livemode
        and price_data.get("active")
        and price_data.get("livemode") is mode.livemode
        and price_data.get("product") == product_id
        and price_data.get("unit_amount") == unit_amount
        and price_data.get("currency") == currency.lower()
        and interval == expected_interval
    ):
        raise RuntimeError("Stripe Product/Price does not match the requested environment and plan")


async def run(arguments: argparse.Namespace) -> int:
    settings = Settings.load(PROJECT_ROOT)
    if settings.discord_owner_user_id is None:
        raise RuntimeError("DISCORD_OWNER_USER_ID is required for pricing audit")
    database = Database(settings.require_database_url())
    service = MembershipPricingService(database)
    try:
        if arguments.command == "list":
            rows = await service.list_versions(arguments.environment)
            for row in rows:
                print(
                    f"{row.environment} {row.plan_type} {row.pricing_version} "
                    f"{row.currency.upper()} {row.unit_amount / 100:.2f} "
                    f"current={str(row.is_current).lower()} active={str(row.is_active).lower()}"
                )
            return 0
        if arguments.confirm_environment != arguments.environment.lower():
            raise RuntimeError("--confirm-environment must match --environment")
        if arguments.command == "create":
            await _verify_stripe_mapping(
                settings,
                environment=arguments.environment,
                plan=arguments.plan,
                unit_amount=arguments.unit_amount,
                currency=arguments.currency,
                product_id=arguments.product_id,
                price_id=arguments.price_id,
            )
            row = await service.create_version(
                guild_id=settings.discord_guild_id,
                actor_user_id=settings.discord_owner_user_id,
                environment=arguments.environment,
                plan_type=arguments.plan,
                pricing_version=arguments.version,
                unit_amount=arguments.unit_amount,
                currency=arguments.currency,
                stripe_product_id=arguments.product_id,
                stripe_price_id=arguments.price_id,
                make_current=arguments.make_current,
            )
        else:
            versions = await service.list_versions(arguments.environment)
            target = next(
                (
                    item
                    for item in versions
                    if item.plan_type == arguments.plan
                    and item.pricing_version == arguments.version.strip().upper()
                ),
                None,
            )
            if (
                target is None
                or target.stripe_product_id is None
                or target.stripe_price_id is None
            ):
                raise RuntimeError("Pricing version is unavailable or has no Stripe mapping")
            await _verify_stripe_mapping(
                settings,
                environment=arguments.environment,
                plan=arguments.plan,
                unit_amount=target.unit_amount,
                currency=target.currency,
                product_id=target.stripe_product_id,
                price_id=target.stripe_price_id,
            )
            row = await service.switch_current(
                guild_id=settings.discord_guild_id,
                actor_user_id=settings.discord_owner_user_id,
                environment=arguments.environment,
                plan_type=arguments.plan,
                pricing_version=arguments.version,
            )
        print(
            f"pricing_change=APPLIED environment={row.environment} plan={row.plan_type} "
            f"version={row.pricing_version} current={str(row.is_current).lower()}"
        )
        return 0
    finally:
        await database.dispose()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Manage immutable AXIS membership pricing")
    commands = root.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--environment", choices=("test", "live"), required=True)

    create = commands.add_parser("create")
    create.add_argument("--environment", choices=("test", "live"), required=True)
    create.add_argument("--confirm-environment", choices=("test", "live"), required=True)
    create.add_argument("--plan", choices=("DAY_PASS", "MONTHLY"), required=True)
    create.add_argument("--version", required=True)
    create.add_argument("--unit-amount", type=int, required=True)
    create.add_argument("--currency", default="usd")
    create.add_argument("--product-id", required=True)
    create.add_argument("--price-id", required=True)
    create.add_argument("--make-current", action="store_true")

    switch = commands.add_parser("switch")
    switch.add_argument("--environment", choices=("test", "live"), required=True)
    switch.add_argument("--confirm-environment", choices=("test", "live"), required=True)
    switch.add_argument("--plan", choices=("DAY_PASS", "MONTHLY"), required=True)
    switch.add_argument("--version", required=True)
    return root


def main() -> int:
    return asyncio.run(run(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
