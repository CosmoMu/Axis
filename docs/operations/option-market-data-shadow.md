# AXIS Option Market Data Shadow Box

`scripts/compare_option_market_data.py` is a read-only comparison tool. It sends the same eligible,
active Short-Term option requests to Massive and the local Moomoo OpenD adapter, then reports:

- normalized MID price from each provider;
- provider source timestamp and market state;
- absolute and percentage price difference;
- contract-specific unavailable, stale, or invalid errors.

It does not update trades, tracking rows, Discord messages, provider configuration, Moomoo accounts,
orders, or positions. Massive remains the production provider unless a separate reviewed deployment
explicitly changes the runtime wiring.

## Run

```bash
.venv/bin/python scripts/compare_option_market_data.py
.venv/bin/python scripts/compare_option_market_data.py --public-id ST-0003 --json
```

The default query includes at most 50 Short-Term rows whose tracking state is `ACTIVE` or
`OVERNIGHT_ACTIVE` and whose contract has not expired. `--public-id` may be repeated. The script
reads `MASSIVE_API_KEY`, `MOOMOO_OPEND_HOST`, and `MOOMOO_OPEND_PORT` from `.env`; it never prints
their values.

For a Short-Term-specific continuous trial, run:

```bash
.venv/bin/python scripts/validate_moomoo_short_term.py
```

The validator defaults to persistent Moomoo `ORDER_BOOK` push, 30 seconds of warm-up, then twelve
samples at the production five-second polling interval. It uses the server-provided bid/ask
timestamps and calculates the same MID price required by `short_term_tracking.yaml`. It performs no
database writes and obtains one final Massive reference snapshot only for price-difference analysis.

## Current provider boundary

- AXIS Stock Analyst daily stock bars already use Moomoo OpenD. Massive is not needed for that
  stock-history path.
- Signal contract validation, missing entry-price fill, and Short-Term live option tracking currently
  use Massive.
- Swing / LEAPS Active Summary currently uses Massive Options Daily Aggregate close values.
- The Moomoo shadow adapter supports US equity/ETF options and SPX/SPXW index options while keeping
  the canonical AXIS `O:...` contract code outside the adapter.

## 2026-09-02 acceptance snapshot

- Stock snapshot through OpenD: PASS.
- QQQ, ACHR, and SPXW contract-chain resolution: PASS.
- Twenty-one eligible live AXIS Short-Term contracts: twenty available from both providers, with
  observed MID difference between 0% and 1.93%; one illiquid DELL contract exceeded AXIS' 120-second
  freshness threshold on both providers. An earlier sample also caught a transient Moomoo-only stale
  QQQ quote that was current on the next full run.
- Historical option daily close: QQQ matched on the sampled session; SPXW did not. Moomoo historical
  K-line close was `5.70`, Massive daily aggregate close was `4.66`, and the next Moomoo snapshot's
  `prev_close_price` was `4.718`. The providers therefore do not yet have proven equivalent close
  semantics for index options.

### Short-Term continuous trial

- Snapshot mode, 21 contracts × 12 samples: **FAIL**, 91.27% coverage. The failure was caused by
  `get_market_snapshot.update_time` not consistently representing the latest bid/ask timestamp.
- Persistent `ORDER_BOOK` mode with five-second warm-up: **CONDITIONAL**, 97.22% coverage. Missing
  observations occurred while newly subscribed illiquid contracts waited for their first live book
  event.
- Persistent `ORDER_BOOK` mode with 30-second warm-up: **PASS**, 252/252 observations, 100% overall
  and SPXW coverage, 0.0006-second p95 cache-read latency, 2.34% p95 MID difference versus Massive,
  and no stale quote, fatal batch, permission, or connection errors.

The accepted Short-Term candidate is therefore persistent Moomoo `ORDER_BOOK` push, not repeated
Moomoo market snapshots. A production design must keep Massive as cold-start and per-contract
fallback until each Moomoo contract receives a timestamped live book event. This trial does not
change the production provider.

## Cutover gate

Do not replace Massive globally yet. Before a production switch, collect at least five normal U.S.
trading sessions and require:

- contract resolution coverage for every supported AXIS underlying, including SPXW;
- no material increase in stale or unavailable quotes;
- price and timestamp differences within an agreed tolerance for liquid and illiquid contracts;
- restart and OpenD-login recovery evidence;
- an explicit decision for official daily closes. Until close semantics match, keep Massive for
  Swing / LEAPS close-based summaries even if live Short-Term tracking later moves to Moomoo.
