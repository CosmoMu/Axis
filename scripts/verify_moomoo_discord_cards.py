#!/usr/bin/env python3
"""Generate real Moomoo-backed Stock/GEX cards and send them to card testing."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.bot.gex_cards import build_gex_embed  # noqa: E402
from app.bot.stock_analyst_cards import build_stock_analyst_embed  # noqa: E402
from app.config import ConfigurationError, Settings  # noqa: E402
from app.db.bootstrap import load_discord_ids  # noqa: E402
from app.db.session import Database  # noqa: E402
from app.integrations.gex_intraday_data import MoomooGexIntradayProvider  # noqa: E402
from app.integrations.gex_market_data import MoomooGexMarketDataProvider  # noqa: E402
from app.integrations.massive_market_data import verified_ssl_context  # noqa: E402
from app.market_intelligence.stock_analyst.market_data import MoomooDailyBarProvider  # noqa: E402
from app.market_intelligence.stock_analyst.service import AxisStockAnalystService  # noqa: E402
from app.services.gex_explorer import GexExplorerService, GexPolicy  # noqa: E402
from app.services.stock_analyst import StockAnalystPolicy, StockAnalystQueryService  # noqa: E402


async def _send_card(
    session: aiohttp.ClientSession,
    *,
    channel_id: int,
    token: str,
    embed: dict[str, object],
    filename: str,
    image: bytes,
) -> str:
    form = aiohttp.FormData()
    form.add_field("payload_json", json.dumps({"embeds": [embed]}, ensure_ascii=False))
    form.add_field(
        "files[0]",
        image,
        filename=filename,
        content_type="image/png",
    )
    async with session.post(
        f"https://discord.com/api/v10/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}"},
        data=form,
    ) as response:
        payload = await response.json(content_type=None)
        if response.status != 200:
            raise RuntimeError(f"DISCORD_CARD_SEND_FAILED_{response.status}")
        return str(payload["id"])


async def verify(tickers: tuple[str, ...]) -> dict[str, object]:
    settings = Settings.load(PROJECT_ROOT)
    if any(
        provider != "moomoo"
        for provider in (
            settings.stock_market_data_provider,
            settings.gex_market_data_provider,
            settings.gex_intraday_provider,
            settings.option_tracking_provider,
        )
    ):
        raise ConfigurationError("MOOMOO_PRODUCTION_PROVIDER_SELECTION_REQUIRED")
    ids = load_discord_ids(settings.ids_path, settings.discord_guild_id)
    channel_id = int(ids["channels"]["card_testing"])
    actor_id = settings.discord_owner_user_id or 1
    database = Database(settings.require_database_url())
    stock_policy = StockAnalystPolicy.load(
        settings.stock_analyst_policy_path,
        version_override=settings.stock_analyst_policy_version,
    )
    stock = StockAnalystQueryService(
        database,
        AxisStockAnalystService(
            provider=MoomooDailyBarProvider(
                settings.moomoo_host,
                settings.moomoo_port,
                lookback_days=stock_policy.daily_lookback_calendar_days,
            )
        ),
        stock_policy,
    )
    gex_policy = GexPolicy.load(settings.gex_explorer_policy_path)
    gex = GexExplorerService(
        database,
        MoomooGexMarketDataProvider(host=settings.moomoo_host, port=settings.moomoo_port),
        MoomooGexIntradayProvider(
            host=settings.moomoo_host,
            port=settings.moomoo_port,
            interval_minutes=gex_policy.intraday_interval_minutes,
        ),
        gex_policy,
    )
    sent: list[dict[str, object]] = []
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        connector = aiohttp.TCPConnector(ssl=verified_ssl_context())
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for ticker in tickers:
                result = await stock.query(
                    guild_id=settings.discord_guild_id,
                    actor_user_id=actor_id,
                    ticker=ticker,
                    enforce_rate_limits=False,
                )
                filename = f"axis-stock-{ticker.lower()}.png"
                message_id = await _send_card(
                    session,
                    channel_id=channel_id,
                    token=settings.require_token(),
                    embed=build_stock_analyst_embed(result, mode="MEMBER_LOUNGE").to_dict(),
                    filename=filename,
                    image=result.chart_png,
                )
                sent.append(
                    {
                        "tool": "stock",
                        "ticker": ticker,
                        "provider": result.provider,
                        "message_id": message_id,
                    }
                )
            for ticker in tickers:
                result = await gex.query(
                    guild_id=settings.discord_guild_id,
                    actor_user_id=actor_id,
                    ticker=ticker,
                    enforce_rate_limits=False,
                )
                filename = f"axis-gex-{ticker.lower()}.png"
                message_id = await _send_card(
                    session,
                    channel_id=channel_id,
                    token=settings.require_token(),
                    embed=build_gex_embed(result, test_mode=False).to_dict(),
                    filename=filename,
                    image=result.heatmap_png,
                )
                sent.append(
                    {
                        "tool": "gex",
                        "ticker": ticker,
                        "provider": result.provider,
                        "message_id": message_id,
                    }
                )
    finally:
        await database.dispose()
    return {
        "status": "PASS",
        "guild_id": settings.discord_guild_id,
        "channel_id": channel_id,
        "cards": sent,
    }


def main() -> int:
    try:
        payload = asyncio.run(verify(("SPY", "NVDA")))
    except Exception as exc:
        payload = {"status": "FAIL", "error_type": getattr(exc, "code", type(exc).__name__)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
