#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import ssl
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aiohttp  # noqa: E402
import certifi  # noqa: E402
import discord  # noqa: E402
import stripe  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids  # noqa: E402
from app.db.models import MembershipEntitlement, MembershipSession, PaymentEvent  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.domain.enums import EntitlementStatus, MembershipPlanType  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())


async def _verify_database(settings: Settings) -> tuple[int, str]:
    database = Database(settings.require_database_url())
    try:
        async with database.session() as session:
            sessions = list(
                await session.scalars(
                    select(MembershipSession)
                    .where(
                        MembershipSession.guild_id == settings.discord_guild_id,
                        MembershipSession.provider == "stripe",
                        MembershipSession.membership_type.in_(
                            [MembershipPlanType.DAY_PASS.value, MembershipPlanType.MONTHLY.value]
                        ),
                        MembershipSession.used_at.is_not(None),
                    )
                    .order_by(MembershipSession.created_at.desc())
                )
            )
            latest: dict[str, MembershipSession] = {}
            for membership_session in sessions:
                if membership_session.membership_type is not None:
                    latest.setdefault(membership_session.membership_type, membership_session)
            if set(latest) != {
                MembershipPlanType.DAY_PASS.value,
                MembershipPlanType.MONTHLY.value,
            }:
                raise RuntimeError("Completed Day Pass and Monthly sessions were not found")
            user_ids = {item.discord_user_id for item in latest.values()}
            if len(user_ids) != 1:
                raise RuntimeError("Test Checkout sessions are not bound to one Discord user")
            user_id = user_ids.pop()

            entitlements = list(
                await session.scalars(
                    select(MembershipEntitlement).where(
                        MembershipEntitlement.guild_id == settings.discord_guild_id,
                        MembershipEntitlement.discord_user_id == user_id,
                        MembershipEntitlement.provider == "stripe",
                        MembershipEntitlement.status.in_(
                            [
                                EntitlementStatus.ACTIVE.value,
                                EntitlementStatus.CANCEL_AT_PERIOD_END.value,
                            ]
                        ),
                    )
                )
            )
            by_type = {item.entitlement_type: item for item in entitlements}
            day_pass = by_type.get(MembershipPlanType.DAY_PASS.value)
            monthly = by_type.get(MembershipPlanType.MONTHLY.value)
            if day_pass is None or day_pass.unit_amount_at_signup != 999:
                raise RuntimeError("Active Day Pass V1 entitlement was not found")
            if monthly is None or monthly.unit_amount_at_signup != 9999:
                raise RuntimeError("Active Monthly V1 entitlement was not found")
            if not monthly.provider_customer_id or not monthly.provider_subscription_id:
                raise RuntimeError("Monthly provider identifiers were not linked")

            invoice = await session.scalar(
                select(PaymentEvent)
                .where(
                    PaymentEvent.membership_id == monthly.id,
                    PaymentEvent.event_type == "invoice.paid",
                )
                .order_by(PaymentEvent.created_at.desc())
            )
            if invoice is None or invoice.processing_status != "PROCESSED":
                raise RuntimeError("Monthly invoice.paid was not processed")
            return user_id, monthly.provider_subscription_id
    finally:
        await database.dispose()


async def _verify_member_role(settings: Settings, user_id: int) -> None:
    discord_ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    member_role_id = discord_ids["roles"]["member"]
    intents = discord.Intents.none()
    intents.guilds = True
    intents.members = True
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    client = discord.Client(
        intents=intents,
        connector=aiohttp.TCPConnector(ssl=ssl_context),
    )
    connect_task = None
    try:
        await client.login(settings.require_token())
        connect_task = asyncio.create_task(client.connect(reconnect=False))
        await client.wait_until_ready()
        guild = client.get_guild(settings.discord_guild_id)
        if guild is None:
            raise RuntimeError("AXIS Guild was not found")
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        if member_role_id not in {role.id for role in member.roles}:
            raise RuntimeError("Member Role was not synchronized")
    finally:
        await client.close()
        if connect_task is not None:
            await asyncio.gather(connect_task, return_exceptions=True)


async def verify() -> None:
    settings = Settings.load(PROJECT_ROOT)
    if not settings.stripe_configuration_ready():
        raise RuntimeError("Stripe Test configuration is incomplete")
    if not settings.stripe_secret_key.startswith("sk_test_"):
        raise RuntimeError("Stripe key is not a Test Mode key")
    user_id, subscription_id = await _verify_database(settings)
    subscription = await asyncio.to_thread(
        stripe.StripeClient(settings.stripe_secret_key).v1.subscriptions.retrieve,
        subscription_id,
    )
    if subscription.status != "active" or subscription.cancel_at_period_end:
        raise RuntimeError("Monthly Test subscription is not actively auto-renewing")
    await _verify_member_role(settings, user_id)


def main() -> int:
    asyncio.run(verify())
    print("stripe_test_e2e=PASS")
    print("day_pass=ACTIVE")
    print("monthly=ACTIVE auto_renew=ENABLED invoice_paid=PROCESSED")
    print("discord_member_role=PRESENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
