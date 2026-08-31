#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.stripe_gateway import StripeSdkGateway  # noqa: E402
from app.services.membership_access import (  # noqa: E402
    MembershipAcknowledgementService,
    MembershipPriceCatalog,
)
from app.services.membership_stripe import MembershipStripeService  # noqa: E402
from app.services.trading_calendar import TradingCalendarService  # noqa: E402


async def reconcile(*, apply: bool, confirmed_environment: str | None) -> int:
    settings = Settings.load(PROJECT_ROOT)
    stripe_config = settings.stripe_config()
    active = stripe_config.active
    if not stripe_config.runtime_ready():
        raise RuntimeError("Selected Stripe environment is not runtime-ready")
    if apply and confirmed_environment != stripe_config.mode.value:
        raise RuntimeError("--confirm-environment must match STRIPE_MODE when using --apply")
    if settings.discord_owner_user_id is None:
        raise RuntimeError("DISCORD_OWNER_USER_ID is required for reconciliation audit")
    database = Database(settings.require_database_url())
    try:
        gateway = StripeSdkGateway(
            secret_key=active.secret_key,
            webhook_secret=active.webhook_secret,
            success_url=active.success_url or "",
            cancel_url=active.cancel_url or "",
            portal_return_url=active.portal_return_url or "",
            mode=stripe_config.mode,
        )
        acknowledgements = MembershipAcknowledgementService(database)
        service = MembershipStripeService(
            database,
            gateway,
            TradingCalendarService(),
            acknowledgements,
            MembershipPriceCatalog(
                database, environment=stripe_config.mode.database_value
            ),
            mode=stripe_config.mode,
            payments_enabled=stripe_config.payments_enabled,
        )
        result = await service.reconcile_subscriptions(
            settings.discord_guild_id,
            actor_user_id=settings.discord_owner_user_id,
            apply=apply,
        )
    finally:
        await database.dispose()
    counts = Counter(item.action for item in result.items)
    print(f"stripe_reconciliation={'APPLIED' if apply else 'DRY_RUN'}")
    print(f"environment={result.environment}")
    print(f"provider_subscriptions={result.provider_count}")
    print(f"local_memberships={result.local_count}")
    print(f"repairs={result.repaired_count}")
    for action, count in sorted(counts.items()):
        print(f"action_{action.lower()}={count}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile Stripe, AXIS membership, and Discord role source state"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-environment", choices=("test", "live"))
    arguments = parser.parse_args()
    return asyncio.run(
        reconcile(
            apply=arguments.apply,
            confirmed_environment=arguments.confirm_environment,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
