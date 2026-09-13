# AXIS Moomoo Market Data Operations

## Production configuration

AXIS selects each provider explicitly:

```text
STOCK_MARKET_DATA_PROVIDER=moomoo
GEX_MARKET_DATA_PROVIDER=moomoo
GEX_INTRADAY_PROVIDER=moomoo
OPTION_TRACKING_PROVIDER=moomoo
```

Accepted values are only `moomoo` and `massive`; invalid values stop startup. There is no automatic
fallback. With all four values set to `moomoo`, `MASSIVE_API_KEY` may be empty and Massive market
providers are not instantiated. Massive adapters remain in the repository only for deliberate
rollback.

## OpenD and quote rights

- Keep a supported Moomoo OpenD running and logged in on the configured local endpoint.
- Python SDK and OpenD must be compatible; the production gate used SDK `10.10.7008`.
- Required equity fields: bid, ask, last, volume, update time, Daily and 1m/5m OHLCV.
- Required option fields: strike, expiry, side, bid, ask, last, volume, OI, IV, delta, gamma and
  update time.
- AXIS GEX does not require full order-book depth. OPRA best bid/ask is useful for tracking and
  validation, while snapshot update time drives freshness.

## Data flows

- `/stock`: `MoomooDailyBarProvider` → unchanged AXIS/Cosmos deterministic Stock Analyst → card/PNG.
- `/gex`: `MoomooGexMarketDataProvider` + `MoomooGexIntradayProvider` → unchanged shared GEX engine
  and heatmap. Option-chain windows are at most 30 days; snapshot requests are batched; chain calls
  use a process-wide rolling limiter below OpenD's 10/30s limit.
- Short-Term and Simple Swing: `MoomooOptionMarketDataProvider` preserves canonical OCC identifiers,
  configured BID/MID/LAST semantics, provider timestamps, stale checks and LAST outlier protection.
- Post-close Swing/LEAPS summaries: `MoomooMarketDataClient`; option prices are never replaced with
  underlying stock prices.

## Freshness and closed markets

Provider `update_time` is authoritative. Request receipt time must never make stale data fresh.
During closed markets, `/stock` and permitted GEX output are labeled latest-available/closed-market.
Market tracking retains its existing stale rejection and trading-session scheduling.

## SPX

Moomoo currently supplies SPXW chain and option snapshots but rejects the `US..SPX` underlying
snapshot. AXIS returns `SPX_PROVIDER_UNSUPPORTED`, never proxies SPY, and keeps other tickers live.

## Failure handling

OpenD unavailable, SDK import failure, login/permission failure, subscription failure, stale quote,
incomplete expiry, minimum GEX coverage and quota/rate-limit conditions fail closed. Existing
deduplicated System Alert/Recovery handles service-level failures; individual bad contracts remain
isolated where the tracking boundary permits.

## Verification

```text
.venv/bin/python scripts/verify_stock_analyst.py SPY QQQ NVDA TSLA AAPL META PLTR AMD
.venv/bin/python scripts/verify_gex_explorer.py SPY QQQ NVDA TSLA AAPL --skip-invalid
.venv/bin/python scripts/verify_moomoo_discord_cards.py
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python -m compileall -q app scripts tests
.venv/bin/python scripts/verify_database.py
.venv/bin/python scripts/verify_discord_runtime.py
.venv/bin/python scripts/bootstrap_discord.py
```

## Deliberate rollback

Only if a valid Massive key/entitlement exists, set the four provider variables to `massive`, set
`MASSIVE_API_KEY`, restart AXIS BOT, and rerun the verifiers. Do not delete or rewrite market-data,
Signal, Trade, Results, Membership or Mentor records. Never silently fall back after a Moomoo error.

## Separate public website boundary

The public Sites project under `website/` is a separate deployment and does not call the Python
Bot GEX service. Its current serverless `/api/gex` implementation remains Massive-based. This does
not affect Discord `/gex`, `/stock`, tracking or post-close production traffic, but the website API
will require a separate remote-Moomoo architecture because a hosted worker cannot connect directly
to local OpenD. Do not describe the website endpoint as migrated until that separate design ships.
