#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.models import ShortTermTracking, Trade  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.massive_market_data import (  # noqa: E402
    MarketPriceRequest,
    MassiveMarketDataProvider,
)
from app.integrations.moomoo_market_data import (  # noqa: E402
    MoomooOptionMarketDataProvider,
)
from app.integrations.option_market_data_shadow import (  # noqa: E402
    OptionMarketComparison,
    OptionMarketDataShadowBox,
)
from app.services.short_term_policy import ShortTermTrackingPolicy  # noqa: E402

ET = ZoneInfo("America/New_York")
ACTIVE_TRACKING_STATES = ("ACTIVE", "OVERNIGHT_ACTIVE")


async def _active_requests(
    database: Database,
    *,
    public_ids: tuple[str, ...],
    limit: int,
) -> tuple[MarketPriceRequest, ...]:
    today = datetime.now(ET).date()
    statement = (
        select(Trade.public_trade_id, Trade.ticker, ShortTermTracking.option_ticker)
        .join(ShortTermTracking, ShortTermTracking.trade_id == Trade.id)
        .where(
            ShortTermTracking.tracking_state.in_(ACTIVE_TRACKING_STATES),
            Trade.expiry >= today,
        )
        .order_by(Trade.public_trade_id)
        .limit(limit)
    )
    if public_ids:
        statement = statement.where(Trade.public_trade_id.in_(public_ids))
    async with database.session() as session:
        rows = (await session.execute(statement)).all()
    return tuple(
        MarketPriceRequest(public_trade_id, ticker, option_ticker)
        for public_trade_id, ticker, option_ticker in rows
    )


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.0001")))


def _serialize(row: OptionMarketComparison) -> dict[str, Any]:
    return {
        "public_trade_id": row.key,
        "option_ticker": row.option_ticker,
        "absolute_price_difference": _decimal(row.absolute_price_difference),
        "primary_relative_difference_pct": _decimal(
            row.primary_relative_difference_pct
        ),
        "timestamp_difference_seconds": _decimal(row.timestamp_difference_seconds),
        "providers": {
            item.provider: {
                "price": _decimal(item.price),
                "price_source": item.price_source,
                "source_timestamp": (
                    item.source_timestamp.isoformat() if item.source_timestamp else None
                ),
                "market_status": item.market_status,
                "error_code": item.error_code,
            }
            for item in row.observations
        },
    }


def _print_human(rows: tuple[OptionMarketComparison, ...]) -> None:
    print("AXIS option market-data shadow comparison (production provider unchanged)")
    print("ID        Massive       Moomoo        Diff %      Errors")
    for row in rows:
        observations = {item.provider: item for item in row.observations}
        massive = observations["MASSIVE"]
        moomoo = observations["MOOMOO"]
        errors = ", ".join(
            f"{item.provider}:{item.error_code}"
            for item in row.observations
            if item.error_code
        )
        print(
            f"{row.key:<9} "
            f"{str(massive.price or '-'):>12} "
            f"{str(moomoo.price or '-'):>12} "
            f"{str(_decimal(row.primary_relative_difference_pct) or '-'):>10} "
            f"{errors or '-'}"
        )


async def run(args: argparse.Namespace) -> int:
    settings = Settings.load(PROJECT_ROOT)
    if not settings.massive_api_key:
        raise ConfigurationError("MASSIVE_API_KEY is required for provider comparison.")
    policy = ShortTermTrackingPolicy.load(settings.short_term_tracking_config_path)
    database = Database(settings.require_database_url())
    try:
        requests = await _active_requests(
            database,
            public_ids=tuple(value.upper() for value in args.public_id),
            limit=args.limit,
        )
    finally:
        await database.dispose()
    if not requests:
        message = (
            json.dumps({"error": "NO_ELIGIBLE_ACTIVE_CONTRACTS"})
            if args.json
            else "No eligible active contracts."
        )
        print(message)
        return 1

    box = OptionMarketDataShadowBox(
        {
            "MASSIVE": MassiveMarketDataProvider(
                api_key=settings.massive_api_key,
                price_source=policy.price_source,
                max_quote_age_seconds=policy.max_quote_age_seconds,
                last_trade_quote_guard_pct=policy.last_trade_quote_guard_pct,
                base_url=settings.massive_base_url,
            ),
            "MOOMOO": MoomooOptionMarketDataProvider(
                host=settings.moomoo_host,
                port=settings.moomoo_port,
                price_source=policy.price_source,
                max_quote_age_seconds=policy.max_quote_age_seconds,
                last_trade_quote_guard_pct=policy.last_trade_quote_guard_pct,
            ),
        },
        primary_provider="MASSIVE",
        candidate_provider="MOOMOO",
    )
    rows = await box.compare(requests)
    if args.json:
        print(json.dumps({"comparisons": [_serialize(row) for row in rows]}, indent=2))
    else:
        _print_human(rows)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Massive/Moomoo option quote comparison. This script never changes "
            "the AXIS production provider."
        )
    )
    parser.add_argument(
        "--public-id",
        action="append",
        default=[],
        help="Compare only this active AXIS trade ID; may be repeated.",
    )
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 401))
    parser.add_argument("--json", action="store_true")
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
