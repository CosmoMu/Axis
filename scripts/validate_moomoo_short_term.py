#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
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
    MarketDataProvider,
    MarketDataProviderError,
    MarketPrice,
    MarketPriceRequest,
    MassiveMarketDataProvider,
)
from app.integrations.moomoo_market_data import (  # noqa: E402
    MoomooOptionMarketDataProvider,
    MoomooOptionOrderBookProvider,
)
from app.services.short_term_policy import ShortTermTrackingPolicy  # noqa: E402

ET = ZoneInfo("America/New_York")
ACTIVE_TRACKING_STATES = ("ACTIVE", "OVERNIGHT_ACTIVE")


@dataclass(frozen=True, slots=True)
class TrialSample:
    latency_seconds: float
    prices: tuple[MarketPrice, ...]
    failures: dict[str, str]
    fatal_error: str | None


async def _active_requests(database: Database) -> tuple[MarketPriceRequest, ...]:
    today = datetime.now(ET).date()
    statement = (
        select(Trade.public_trade_id, Trade.ticker, ShortTermTracking.option_ticker)
        .join(ShortTermTracking, ShortTermTracking.trade_id == Trade.id)
        .where(
            ShortTermTracking.tracking_state.in_(ACTIVE_TRACKING_STATES),
            Trade.expiry >= today,
        )
        .order_by(Trade.public_trade_id)
        .limit(400)
    )
    async with database.session() as session:
        rows = (await session.execute(statement)).all()
    return tuple(
        MarketPriceRequest(public_trade_id, ticker, option_ticker)
        for public_trade_id, ticker, option_ticker in rows
    )


async def _sample(
    provider: MarketDataProvider,
    requests: tuple[MarketPriceRequest, ...],
) -> TrialSample:
    started = time.perf_counter()
    fatal_error = None
    try:
        prices = await provider.fetch_prices(requests)
    except MarketDataProviderError as exc:
        prices = ()
        fatal_error = exc.code
    latency = time.perf_counter() - started
    failures = {failure.key: failure.error_code for failure in provider.last_failures}
    if fatal_error and failures and all(key in failures for key in (item.key for item in requests)):
        fatal_error = None
    return TrialSample(latency, prices, failures, fatal_error)


async def _massive_reference(
    provider: MassiveMarketDataProvider,
    requests: tuple[MarketPriceRequest, ...],
) -> tuple[dict[str, MarketPrice], dict[str, str]]:
    try:
        prices = await provider.fetch_prices(requests)
        fatal = None
    except MarketDataProviderError as exc:
        prices = ()
        fatal = exc.code
    failures = {failure.key: failure.error_code for failure in provider.last_failures}
    if fatal:
        for request in requests:
            failures.setdefault(request.key, fatal)
    return {price.key: price for price in prices}, failures


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _decimal(value: Decimal | float | None, places: str = "0.0001") -> str | None:
    if value is None:
        return None
    return str(Decimal(str(value)).quantize(Decimal(places)))


def _report(
    requests: tuple[MarketPriceRequest, ...],
    samples: list[TrialSample],
    massive_prices: dict[str, MarketPrice],
    massive_failures: dict[str, str],
    *,
    mode: str,
    poll_seconds: int,
    max_quote_age_seconds: int,
) -> dict[str, Any]:
    expected = len(requests) * len(samples)
    successes = sum(len(sample.prices) for sample in samples)
    coverage = Decimal(successes) / Decimal(expected) * Decimal("100") if expected else Decimal(0)
    failure_counts = Counter(
        code for sample in samples for code in sample.failures.values()
    )
    fatal_errors = [sample.fatal_error for sample in samples if sample.fatal_error]
    success_by_contract: Counter[str] = Counter()
    failure_by_contract: dict[str, Counter[str]] = defaultdict(Counter)
    last_moomoo_prices: dict[str, MarketPrice] = {}
    for sample in samples:
        for price in sample.prices:
            success_by_contract[price.key] += 1
            last_moomoo_prices[price.key] = price
        for key, code in sample.failures.items():
            failure_by_contract[key][code] += 1

    differences = []
    for key, moomoo_price in last_moomoo_prices.items():
        massive_price = massive_prices.get(key)
        if massive_price is None or massive_price.price <= 0:
            continue
        differences.append(
            float(abs(moomoo_price.price - massive_price.price) / massive_price.price * 100)
        )

    spx_keys = {
        request.key for request in requests if request.option_ticker.startswith("O:SPXW")
    }
    spx_expected = len(spx_keys) * len(samples)
    spx_successes = sum(success_by_contract[key] for key in spx_keys)
    spx_coverage = (
        Decimal(spx_successes) / Decimal(spx_expected) * Decimal("100")
        if spx_expected
        else None
    )
    latency_p95 = _percentile([sample.latency_seconds for sample in samples], 0.95)
    difference_p95 = _percentile(differences, 0.95)
    has_isolated_failure = any(sample.failures and sample.prices for sample in samples)

    hard_pass = (
        coverage >= Decimal("99.5")
        and not fatal_errors
        and latency_p95 is not None
        and latency_p95 <= 2.0
        and (spx_coverage is None or spx_coverage == Decimal("100"))
        and (difference_p95 is None or difference_p95 <= 5.0)
    )
    conditional_pass = (
        coverage >= Decimal("95")
        and not fatal_errors
        and latency_p95 is not None
        and latency_p95 <= 3.0
        and (spx_coverage is None or spx_coverage >= Decimal("95"))
        and (difference_p95 is None or difference_p95 <= 5.0)
    )
    verdict = "PASS" if hard_pass else "CONDITIONAL" if conditional_pass else "FAIL"

    return {
        "verdict": verdict,
        "production_provider_changed": False,
        "database_writes": 0,
        "requirements": {
            "moomoo_mode": mode,
            "price_source": "MID",
            "poll_seconds": poll_seconds,
            "max_quote_age_seconds": max_quote_age_seconds,
            "batch_size_limit": 400,
        },
        "summary": {
            "contracts": len(requests),
            "samples": len(samples),
            "expected_observations": expected,
            "successful_observations": successes,
            "coverage_pct": _decimal(coverage),
            "batch_latency_p95_seconds": _decimal(latency_p95),
            "massive_price_difference_p95_pct": _decimal(difference_p95),
            "spxw_coverage_pct": _decimal(spx_coverage),
            "fatal_batch_errors": fatal_errors,
            "failure_counts": dict(sorted(failure_counts.items())),
            "partial_failure_isolation_observed": has_isolated_failure,
        },
        "contracts": [
            {
                "public_trade_id": request.key,
                "option_ticker": request.option_ticker,
                "successful_samples": success_by_contract[request.key],
                "sample_count": len(samples),
                "failure_counts": dict(sorted(failure_by_contract[request.key].items())),
                "massive_reference_error": massive_failures.get(request.key),
            }
            for request in requests
        ],
    }


async def run(args: argparse.Namespace) -> int:
    settings = Settings.load(PROJECT_ROOT)
    if not settings.massive_api_key:
        raise ConfigurationError("MASSIVE_API_KEY is required for the final reference snapshot.")
    policy = ShortTermTrackingPolicy.load(settings.short_term_tracking_config_path)
    database = Database(settings.require_database_url())
    try:
        requests = await _active_requests(database)
    finally:
        await database.dispose()
    if not requests:
        print(json.dumps({"verdict": "FAIL", "error": "NO_ELIGIBLE_ACTIVE_CONTRACTS"}))
        return 1

    if args.mode == "order-book":
        moomoo: MarketDataProvider = MoomooOptionOrderBookProvider(
            host=settings.moomoo_host,
            port=settings.moomoo_port,
            price_source=policy.price_source,
            max_quote_age_seconds=policy.max_quote_age_seconds,
        )
        await moomoo.prepare(requests)  # type: ignore[attr-defined]
        await asyncio.sleep(args.warmup_seconds)
    else:
        moomoo = MoomooOptionMarketDataProvider(
            host=settings.moomoo_host,
            port=settings.moomoo_port,
            price_source=policy.price_source,
            max_quote_age_seconds=policy.max_quote_age_seconds,
            last_trade_quote_guard_pct=policy.last_trade_quote_guard_pct,
        )
    samples = []
    try:
        for index in range(args.samples):
            sample_started = time.monotonic()
            samples.append(await _sample(moomoo, requests))
            if index + 1 < args.samples:
                elapsed = time.monotonic() - sample_started
                await asyncio.sleep(max(0, args.interval_seconds - elapsed))
    finally:
        close = getattr(moomoo, "close", None)
        if close is not None:
            await close()

    massive = MassiveMarketDataProvider(
        api_key=settings.massive_api_key,
        price_source=policy.price_source,
        max_quote_age_seconds=policy.max_quote_age_seconds,
        last_trade_quote_guard_pct=policy.last_trade_quote_guard_pct,
        base_url=settings.massive_base_url,
    )
    massive_prices, massive_failures = await _massive_reference(massive, requests)
    report = _report(
        requests,
        samples,
        massive_prices,
        massive_failures,
        mode=args.mode,
        poll_seconds=policy.poll_seconds,
        max_quote_age_seconds=policy.max_quote_age_seconds,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["verdict"] != "FAIL" else 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Moomoo acceptance trial for AXIS Short-Term tracking."
    )
    parser.add_argument("--mode", choices=("snapshot", "order-book"), default="order-book")
    parser.add_argument("--samples", type=int, default=12, choices=range(1, 121))
    parser.add_argument("--interval-seconds", type=int, default=5, choices=range(1, 61))
    parser.add_argument("--warmup-seconds", type=int, default=30, choices=range(0, 61))
    return asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
