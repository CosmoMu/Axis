#!/usr/bin/env python3
"""Run secret-safe, read-only AXIS Research E2E validation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from app.config import Settings  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.gex_intraday_data import MassiveGexIntradayProvider  # noqa: E402
from app.integrations.gex_market_data import MassiveGexMarketDataProvider  # noqa: E402
from app.integrations.model_router import ModelRouter  # noqa: E402
from app.market_intelligence.research_engine.agents import ResearchAgentRunner  # noqa: E402
from app.market_intelligence.research_engine.memory import ResearchMemoryStore  # noqa: E402
from app.market_intelligence.research_engine.outcomes import ResearchOutcomeService  # noqa: E402
from app.market_intelligence.research_engine.policy import ResearchPolicy  # noqa: E402
from app.market_intelligence.research_engine.providers import (  # noqa: E402
    AxisGexResearchProvider,
    AxisTechnicalResearchProvider,
    MassiveFundamentalsProvider,
    MassiveNewsMacroProvider,
    MassiveSentimentProvider,
)
from app.market_intelligence.research_engine.providers.base import (  # noqa: E402
    MassiveResearchHttpClient,
)
from app.market_intelligence.research_engine.service import ResearchService  # noqa: E402
from app.market_intelligence.stock_analyst import AxisStockAnalystService  # noqa: E402
from app.market_intelligence.stock_analyst.market_data import MassiveDailyBarProvider  # noqa: E402
from app.services.gex_explorer import GexExplorerService, GexPolicy  # noqa: E402
from app.services.stock_analyst import StockAnalystPolicy, StockAnalystQueryService  # noqa: E402
from app.services.trading_calendar import TradingCalendarService  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+", help="Ticker symbols to validate")
    return parser.parse_args()


async def run(tickers: list[str]) -> list[dict[str, object]]:
    settings = Settings.load(PROJECT_ROOT)
    settings.assert_research_safety()
    policy = ResearchPolicy.load(
        settings.research_policy_path,
        version_override=settings.research_policy_version,
    )
    stock_policy = StockAnalystPolicy.load(
        settings.stock_analyst_policy_path,
        version_override=settings.stock_analyst_policy_version,
    )
    stock = StockAnalystQueryService(
        Database(settings.require_database_url()),
        AxisStockAnalystService(
            provider=MassiveDailyBarProvider(
                api_key=settings.massive_api_key,
                base_url=settings.massive_base_url,
                timeout_seconds=stock_policy.timeout_seconds,
                lookback_days=stock_policy.daily_lookback_calendar_days,
                concurrency=stock_policy.provider_concurrency,
            )
        ),
        stock_policy,
    )
    database = stock.database
    gex_policy = GexPolicy.load(settings.gex_explorer_policy_path)
    gex = GexExplorerService(
        database,
        MassiveGexMarketDataProvider(
            api_key=settings.massive_api_key,
            base_url=settings.massive_base_url,
            concurrency=gex_policy.provider_concurrency,
        ),
        MassiveGexIntradayProvider(
            api_key=settings.massive_api_key,
            base_url=settings.massive_base_url,
            interval_minutes=gex_policy.intraday_interval_minutes,
        ),
        gex_policy,
    )
    http = MassiveResearchHttpClient(
        api_key=settings.massive_api_key,
        base_url=settings.massive_base_url,
        timeout_seconds=policy.provider_timeout_seconds,
    )
    service = ResearchService(
        database,
        policy=policy,
        technical_provider=AxisTechnicalResearchProvider(stock),
        gex_provider=AxisGexResearchProvider(gex),
        fundamentals_provider=MassiveFundamentalsProvider(http),
        news_provider=MassiveNewsMacroProvider(
            http,
            max_items=policy.max_news_items,
            max_source_text_chars=policy.max_source_text_chars,
        ),
        sentiment_provider=MassiveSentimentProvider(http, max_items=policy.max_news_items),
        agents=ResearchAgentRunner(
            api_key=settings.require_openai_api_key(),
            router=ModelRouter.load(settings.llm_routing_path),
        ),
        memory=ResearchMemoryStore(database),
        outcomes=ResearchOutcomeService(
            database,
            stock.analyst.provider,
            TradingCalendarService(),
            benchmark_ticker=policy.benchmark_ticker,
            horizons=policy.outcome_horizons,
        ),
    )
    output: list[dict[str, object]] = []
    try:
        for ticker in tickers:
            started = perf_counter()
            try:
                result = await service.query(
                    guild_id=settings.discord_guild_id,
                    actor_user_id=settings.discord_owner_user_id,
                    ticker=ticker,
                    enforce_rate_limits=False,
                )
                output.append(
                    {
                        "ticker": result.view.ticker,
                        "status": "INSUFFICIENT" if result.view.insufficient_data else "PASS",
                        "stance": result.view.research_stance,
                        "coverage": result.view.coverage_score,
                        "confidence": result.view.research_confidence,
                        "cache_hit": result.cache_hit,
                        "latency_ms": round((perf_counter() - started) * 1000),
                        "llm_calls": result.llm_calls,
                        "input_tokens": sum(
                            item.input_tokens or 0 for item in result.agent_outputs
                        ),
                        "output_tokens": sum(
                            item.output_tokens or 0 for item in result.agent_outputs
                        ),
                        "component_statuses": {
                            item.component: item.status for item in result.pack.components
                        },
                        "component_errors": {
                            item.component: item.error_type
                            for item in result.pack.components
                            if item.error_type
                        },
                    }
                )
            except Exception as exc:
                output.append(
                    {
                        "ticker": ticker.upper(),
                        "status": "FAIL",
                        "error_type": getattr(exc, "code", type(exc).__name__),
                        "error_detail": str(exc)[:200],
                        "latency_ms": round((perf_counter() - started) * 1000),
                    }
                )
    finally:
        await database.dispose()
    return output


def main() -> int:
    results = asyncio.run(run([item.upper() for item in _arguments().tickers]))
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] != "FAIL" for item in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
