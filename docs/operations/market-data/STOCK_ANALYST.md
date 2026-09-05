# AXIS Stock Analyst Operations

**Phase:** `MEMBER LOUNGE LIVE / POST-LAUNCH MONITORING`

**Command:** `/stock ticker:TICKER`

**Access:** Member / Manager / Owner in `🛋️・member-lounge`; Owner maintenance in `🧪・card-testing`

**Strategy version:** `COSMOS_STOCK_ANALYST_V0_1`

## Runtime boundary

`/stock` is an on-demand, read-only market-analysis surface. Discord defers the interaction, then
normalizes the symbol, loads market data, runs deterministic analysis once, and renders a card and
PNG from the same structured result. A plain ticker message never triggers it.

The Member Lounge path is fail-closed. It requires the exact configured Guild, exact
`🛋️・member-lounge` channel, and Member / Manager / Owner access. Newcomer and `@everyone` are
blocked. Owner retains the card-testing maintenance path; all other channels are rejected.

The command never creates or changes Signal, Trade, Result, Mentor, public Analysis, Tracking,
Membership or broker state. It never invokes Moomoo or the Owner Personal Execution Layer.

## Cosmos source and shared AXIS architecture

The recovered source of truth is Cosmos Market Stock Analyst v0.1:

- `apps/cosmos_market/stock_analysis_service.py`
- `packages/cosmos_core/market/stock_analysis.py`
- `packages/cosmos_core/price_action/indicators.py`
- `packages/cosmos_core/market/sector_rotation.py`
- `packages/cosmos_vision/stock_analysis_card.py`
- `packages/cosmos_discord/stock_analysis_formatter.py`

AXIS ports those formulas into `app/market_intelligence/stock_analyst/`. The existing Analysis Fusion
pipeline and `/stock` both use `AxisStockAnalystService` and the same deterministic engine; there is
no second, divergent Stock Analyst strategy. Discord-only cache, authorization, rate limiting and
audit behavior live in `app/services/stock_analyst.py` and `app/bot/cogs/stock_analyst.py`.

## Market data and freshness

Massive is the Phase 1 provider. It supplies current/latest price, market status, source timestamp
and adjusted daily OHLCV. The request uses a 550-calendar-day lookback and requires at least 120
valid daily sessions. The engine uses one Daily timeframe because recovered Cosmos v0.1 itself used
Daily bars; no unrecovered intraday or higher-timeframe analysis was invented. Optional sector ETF,
benchmark and sector-candidate daily bars are loaded through the same provider boundary.

SPX uses its native index symbol. It is never silently mapped to SPY. Missing or unsupported symbols
fail closed.

The card displays the source time in ET and the provider. During an open market, data older than 900
seconds is labeled `STALE DATA`. Closed/after-hours output is labeled as based on the latest available
market data and is not described as live.

## Deterministic strategy

### Structure and indicators

- HLX High/Low EMA channels: 25 and 90 sessions.
- Confirmed, non-repainting ZCZL swing pivots: 3, 6 and 13 sessions.
- MACD: EMA 12 / EMA 26 / signal EMA 9.
- RSI: 14-session simple average gains and losses.
- Price structure: current versus 20-session average, 20 versus 50-session average, and 20/60-session
  returns.
- ATR: 14 sessions, used for level clustering rather than shown as a directional signal.
- Money-flow proxy: 20 daily bars, combining close location within each bar, signed OHLCV and OBV
  direction. This is explicitly an OHLCV pressure proxy, not institutional order flow.

Cosmos v0.1 does not calculate Bollinger Bands, VWAP or RVOL. AXIS therefore reports RVOL as
unavailable instead of inventing it.

### POC and Value Area

The volume-profile proxy uses the latest 80 daily bars and 24 equal price bins. Each bar's reported
volume is distributed uniformly across bins touched by that bar's high/low range. POC is the bin with
the largest assigned volume. Starting at POC, the algorithm expands toward the larger adjacent bin
until 70% of modeled volume is covered; the resulting outer edges are VAL and VAH. These values are
OHLCV-derived proxies, not exchange volume-at-price observations.

### Support and resistance

Candidates come from confirmed ZCZL support/resistance, HLX 25/90 channel edges, 20D and 60D
highs/lows, POC, VAL and VAH. Nearby candidates are clustered with tolerance
`max(ATR14 × 0.35, price × 0.0025, 0.01)`. Cluster price is strength-weighted; source confluence adds
strength. Levels at/below current price are support and levels above it are resistance. The engine
retains at most five per side; the mobile card displays the nearest two.

### Bias

The 0–100 Cosmos trend score is:

- HLX 30%
- ZCZL 25%
- MACD 14%
- price structure 14%
- RSI 7%
- OHLCV flow proxy 10%

When valid sector-rotation context is available, Cosmos applies 90% technical score plus 10% sector
strength. Labels use the original thresholds: `>=68 BULLISH`, `>=55 NEUTRAL → BULLISH`, `<=32
BEARISH`, `<=45 NEUTRAL → BEARISH`, otherwise `NEUTRAL`.

### Scenarios, triggers, targets and invalidation

The engine always builds the recovered three structured paths: bullish continuation, range/base and
bearish breakdown. It derives triggers, targets and invalidation from the computed support,
resistance, volume-profile and structure levels—never fixed percentage targets. Raw weights are
`35 + conviction × 0.45`, `40 - conviction × 0.15`, and `max(5, 25 - conviction × 0.30)`, then
normalized to 100 using Cosmos v0.1 direction/conviction rules.

The card reuses the Analysis Fusion dominance gate: the top path is promoted only when its weight is
at least 50 and leads the next path by at least 10 points. Otherwise it says the structure is unclear
and shows the nearest support/resistance. Weights are model scenario weights, not win rates or
calibrated probabilities.

## Card and chart

The card label is exactly `AXIS STOCK ANALYST · TEST`. It shows price, structure/bias, two relevant
supports and resistances, POC/VA, material indicators, OHLCV pressure proxy, deterministic triggers,
scenario/weight when dominant, source time/provider/cache/latency/version, and an educational-use
disclaimer.

The deterministic 1900×1160 PNG uses 82 real Daily OHLCV candles, the same levels and scenario object
as the card, HLX 25/90, confirmed ZCZL 3/6/13, POC/VA, an OHLCV profile and a structural path in empty
future space. It never fabricates future candles and does not use image generation.

## LLM boundary

The current version makes no LLM call. All numbers and wording selection are deterministic. If a later release
adds an LLM rewrite, it must use the existing workload router, receive only the structured result,
and may not change or invent price, indicators, levels, triggers, targets, invalidation or weights.

## Cache, concurrency and rate limits

- Cache: 60 seconds.
- Key: ticker + strategy version + provider + timeframe/config signature.
- Single-flight: concurrent misses for the same key await one provider/calculation/render task.
- Ordinary-member per-user cooldown: 30 seconds.
- Same normalized ticker cooldown across the Guild: 60 seconds.
- Manager and Owner bypass both cooldowns; provider protection still applies.
- Per-guild fresh requests: 20 per rolling minute.
- Excessive-latency warning threshold: 20 seconds.

Changing the strategy version or timeframe signature invalidates existing entries. A cached result
re-evaluates freshness before presentation; stale cache is never presented as live.

## Audit, errors and alerts

Audit actions are `STOCK_ANALYST_REQUESTED`, `STOCK_ANALYST_CACHE_HIT`,
`STOCK_ANALYST_CACHE_MISS`, `STOCK_ANALYST_GENERATED`, `STOCK_ANALYST_FAILED` and
`STOCK_ANALYST_RATE_LIMITED`. Stored metadata is limited to Guild/User IDs, ticker, timestamps,
latency, provider, cache state, version and success/error state.

Discord receives only stable friendly messages. Tracebacks, credentials and provider URLs are not
shown. Existing deduplicated System Alerts/Recovery handle provider, data-quality, calculation,
render, command and excessive-latency failures. `STOCK_ANALYST_LLM_FAILURE` is reserved and cannot
occur while Phase 1 has no LLM stage.

## Verification

```text
.venv/bin/python scripts/verify_stock_analyst.py
.venv/bin/pytest -q tests/test_stock_analyst.py tests/test_axis_market_intelligence.py
.venv/bin/ruff check app tests scripts
.venv/bin/python -m compileall -q app scripts
.venv/bin/pytest -q
.venv/bin/python scripts/verify_discord_runtime.py
```

The real-data verifier covers SPY, QQQ, NVDA, TSLA, AAPL, META, PLTR and AMD, prints no secrets, and
does not create trading-domain records. Unit tests cover recovered Cosmos fixtures, permissions,
cache miss/hit/expiry/separation/versioning, stale labeling, single-flight, limits and card/result
agreement.

## Enable, disable and rollback

Member Lounge production requires:

```text
STOCK_ANALYST_ENABLED=true
STOCK_ANALYST_MODE=MEMBER_LOUNGE
STOCK_ANALYST_POLICY=config/stock_analyst.yaml
STOCK_ANALYST_POLICY_VERSION=COSMOS_STOCK_ANALYST_V0_1
```

To disable, set `STOCK_ANALYST_ENABLED=false` and restart AXIS BOT. To retain Owner-only maintenance
without Member Lounge access, set `STOCK_ANALYST_MODE=TEST` and restart. Neither rollback deletes
data. Because the feature has no business writes, no data rollback is required.
