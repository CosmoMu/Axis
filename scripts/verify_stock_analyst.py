#!/usr/bin/env python3
"""Secret-safe real-data verifier for AXIS Stock Analyst Phase 1."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.market_intelligence.stock_analyst.market_data import (  # noqa: E402
    MassiveDailyBarProvider,
)
from app.market_intelligence.stock_analyst.service import (  # noqa: E402
    AxisStockAnalystService,
)
from app.services.stock_analyst import (  # noqa: E402
    StockAnalystPolicy,
    StockAnalystQueryService,
)


async def verify(tickers: tuple[str, ...]) -> dict[str, object]:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_stock_analyst_safety()
    policy = StockAnalystPolicy.load(
        settings.stock_analyst_policy_path,
        version_override=settings.stock_analyst_policy_version,
    )
    database = Database(settings.require_database_url())
    provider = MassiveDailyBarProvider(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        timeout_seconds=policy.timeout_seconds,
        lookback_days=policy.daily_lookback_calendar_days,
        concurrency=policy.provider_concurrency,
    )
    service = StockAnalystQueryService(
        database,
        AxisStockAnalystService(provider=provider),
        policy,
    )
    results: list[dict[str, object]] = []
    try:
        for index, ticker in enumerate(tickers, start=1):
            started = time.monotonic()
            result = await service.query(
                guild_id=settings.discord_guild_id,
                actor_user_id=settings.discord_owner_user_id or 1,
                ticker=ticker,
                interaction_id=None,
                enforce_rate_limits=False,
            )
            analysis = result.analysis
            results.append(
                {
                    "ticker": ticker,
                    "price": analysis.current_price,
                    "market_timestamp": result.source_timestamp.isoformat(),
                    "market_status": result.market_status,
                    "stale": result.stale,
                    "history_sessions": analysis.history_sessions,
                    "trend": analysis.trend_label,
                    "bias_score": analysis.trend_score,
                    "support": [item.price for item in analysis.support_levels[:2]],
                    "resistance": [item.price for item in analysis.resistance_levels[:2]],
                    "poc": analysis.point_of_control,
                    "vah": analysis.value_area_high,
                    "val": analysis.value_area_low,
                    "scenario": max(
                        analysis.scenarios,
                        key=lambda item: item.model_weight_percent,
                    ).scenario_id,
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "chart_bytes": len(result.chart_png),
                    "order": index,
                }
            )
        started = time.monotonic()
        cached = await service.query(
            guild_id=settings.discord_guild_id,
            actor_user_id=settings.discord_owner_user_id or 1,
            ticker=tickers[0],
            interaction_id=None,
            enforce_rate_limits=False,
        )
        cache_latency = int((time.monotonic() - started) * 1000)
    finally:
        await database.dispose()
    return {
        "status": "PASS",
        "strategy_version": policy.version,
        "provider": provider.name,
        "tickers": results,
        "cache_hit": cached.cache_hit,
        "cache_hit_latency_ms": cache_latency,
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "tickers",
        nargs="*",
        default=["SPY", "QQQ", "NVDA", "TSLA", "AAPL", "META", "PLTR", "AMD"],
    )
    args = parser.parse_args()
    try:
        payload = asyncio.run(verify(tuple(value.upper() for value in args.tickers)))
    except Exception as exc:
        payload = {"status": "FAIL", "error_type": getattr(exc, "code", type(exc).__name__)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
