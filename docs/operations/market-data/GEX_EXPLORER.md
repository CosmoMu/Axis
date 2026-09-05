# AXIS GEX Explorer Operations

**Current mode:** `TEST` / Owner-only / `🧪・card-testing`

## How `/gex` works

The Owner runs `/gex ticker:NVDA`. AXIS normalizes the symbol, acknowledges the interaction, checks
cache and limits, loads the Massive option surface and Massive 1-minute candles, evaluates the
deterministic GEX engine, renders one desktop-first composite chart, and edits the interaction with
one Chinese card plus one PNG. A separate Moomoo shadow comparison runs in the background and never
selects or blocks production output. A plain `NVDA` message does nothing.

## Who can use it

Phase 1 allows only the configured `DISCORD_OWNER_USER_ID` in the configured `card_testing` channel.
Manager, Member, Newcomer, and everyone else receive an ephemeral denial. An Owner request in any
other channel receives an ephemeral Test Mode redirect. Existing Discord blueprint permissions
also keep `🧪・card-testing` Owner + Bot only.

## Test Mode and Member Lounge Mode

`GEX_EXPLORER_MODE=TEST` is the only accepted Phase 1 mode. `MEMBER_LOUNGE` is reserved for Phase 2
and the current startup safety gate rejects it. It must not be enabled until `GEX_TEST_GATE=PASS`,
the Owner says `APPROVE GEX LOUNGE LAUNCH`, Member/Newcomer permission tests pass, and the status
docs are changed from TEST to LIVE.

## Market Data Provider

Phase 1 uses the existing `MASSIVE_API_KEY` and `MASSIVE_BASE_URL` through
`MassiveGexMarketDataProvider` and `MassiveGexIntradayProvider`. The first adapter fetches
underlying/index spot, candidate expirations, and exact-expiry option snapshots. The second fetches
Massive one-minute aggregate bars, keeps only the latest U.S. regular session, de-duplicates
timestamps, and returns up to the configured bar count. If either Massive boundary cannot provide
real data, `/gex` stops with a stable error; it never draws fake candles. SPX is never mapped to SPY.

`MoomooGexIntradayProvider` remains connected through local OpenD only as a background candidate.
`GexIntradayShadowBox` compares bar counts, overlapping timestamps, latest common close, and source
timestamp differences against Massive. Results are structured internal logs only. Moomoo data is
never used in the card or image, and OpenD / entitlement / subscription failure never blocks the
Massive result.

## GEX Formula and Sign Convention

Dollar GEX per 1% underlying move:

`Gamma × Open Interest × 100 contract multiplier × Spot² × 0.01`

Call GEX is positive and Put GEX is negative under the documented dealer-sign estimate. The card
states that this is an assumption rather than observed dealer inventory. Vendor Gamma is preferred;
Black-Scholes Gamma may be derived from vendor IV. Missing OI/Gamma/IV is skipped.

## Expiry Selection and Near-Term Logic

The policy discovers 16 candidate dates and accepts the first 10 complete, non-truncated dates.
Each date must contain both Call and Put contracts and meet `minimum_contracts_per_expiry`. At least
five valid dates are required by current policy. Same-day valid expiry is 0DTE; otherwise the first
valid date is labeled `Near-Term Structure`.

## Zero Gamma, Walls, and Clusters

- Zero Gamma is the nearest interpolated cumulative Net GEX crossing; if no crossing exists, the
  nearest minimum-absolute cumulative point is used.
- Call Wall is the strike with the greatest positive Call GEX.
- Put Wall is the strike with the greatest absolute negative Put GEX.
- Positive/negative zones group adjacent strikes whose side exposure exceeds the configured
  fraction of that side's peak. The peak and zone boundaries always come from actual strikes.

## Gamma Regime, Bias, and Triggers

The configured normalized Net GEX thresholds produce Strong Positive, Positive, Balanced,
Negative, or Strong Negative Gamma. Bias combines Spot vs Zero Gamma with regime. Bullish and
bearish triggers/targets are selected only from Zero Gamma, GEX walls, or signed surface strikes;
no LLM participates.

## Heatmap

The Pillow renderer produces a deterministic 1800x1125 black AXIS image. The left panel uses a
candle-first adaptive axis for real 1-minute candles, current price, nearby upper resistance /
lower support / Gamma-boundary lines, and negative-GEX volatility-acceleration zones. Distant
pressure, support, and Gamma boundaries use full-width top/bottom off-scale rails with actual
prices instead of flattening candle bodies. Distant negative-GEX zones use full-width purple
off-scale bands with actual level ranges, so acceleration structure remains visible on the chart.
Nearby and off-scale labels both preserve the standard terms `Call Wall`, `Put Wall`, and
`0 Gamma`, followed by the Chinese pressure / support / boundary explanation.
The wider right panel shows strike rows, up to five expiration columns, signed cell intensity,
aggregate GEX, and current / boundary / resistance / support markers. Visible explanatory text is
Chinese. It does not use an image-generation model.

## Cache, single-flight, and rate limits

- Cache key: `(ticker, policy version, provider)`.
- Current TTL: 60 seconds.
- Identical concurrent misses share one provider calculation.
- Current user cooldown: 15 seconds.
- Current guild limit: eight fresh calculations per rolling minute.
- Cache hits still respect user cooldown to avoid Discord interaction spam.

Values are maintained in `config/gex_explorer.yaml`, not scattered through handlers.

## Data freshness and market close

The card shows Massive GEX time and Massive 1-minute K-line time, coverage, cache status, and policy
version. Moomoo shadow details remain internal. Data older than the configured threshold is marked
in Chinese as stale. A closed-market result is labeled in Chinese and described as the latest
available snapshot; it is never called live.

## Error handling and System Alerts

Invalid/not-found symbols return short, safe responses without tracebacks. Insufficient coverage,
provider entitlement/rate/network failures, bad data, renderer errors, command failures, and
excessive latency use stable error codes. Operational failures go through the existing deduplicated
System Alert service; a later successful request closes matching fingerprints and sends one
Recovery card when the failure had been notified. Secrets and full provider URLs are never logged.

## Test Gate

Run:

```text
.venv/bin/ruff check app tests scripts
.venv/bin/python -m compileall -q app scripts
.venv/bin/pytest -q
.venv/bin/python scripts/verify_gex_explorer.py
.venv/bin/python scripts/verify_gex_explorer.py RDDT --skip-invalid --output-dir /tmp/gex-review
.venv/bin/python scripts/verify_database.py
.venv/bin/python scripts/verify_discord_runtime.py
```

Also run the repository's Discord blueprint dry-run/permission verification. Review SPY, QQQ,
NVDA, TSLA, AAPL, invalid-symbol, closed-market, partial-expiry, cache, single-flight, cooldown,
global-limit, stale-data, renderer/provider failure, Massive minute-data failure, non-blocking
Moomoo shadow failure, PNG dimensions, Chinese UI, and SPX-entitlement evidence.

## Disable and rollback

To disable `/gex`, set `GEX_EXPLORER_ENABLED=false` in the deployment Secret environment and restart
the Bot. The command is not registered and no data is deleted.

After a future Member Lounge launch, the intended emergency rollback is to change
`GEX_EXPLORER_MODE=MEMBER_LOUNGE` back to `TEST` and restart. Member use stops while Owner testing in
`🧪・card-testing` remains available. Phase 1 deliberately does not accept Member Lounge mode.
