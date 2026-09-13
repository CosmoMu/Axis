# Moomoo Market Data Capability — 2026-09-13

This is a secret-safe record of the real OpenD entitlement gate run before the AXIS production
provider cutover. No trading API or broker write was used.

## Verdict

- OpenD / SDK / quote context / U.S. market state: **PASS**
- U.S. equity snapshots and Daily / 1m / 5m OHLCV: **PASS**
- SPY option chain and required option snapshot fields: **PASS**
- OPRA order book: **PASS for best bid/ask**; the closed-market cached response exposed one level
  and no server-side bid/ask timestamp. Snapshot `update_time` is available and remains the formal
  freshness source for AXIS market tracking.
- Moomoo production migration gate for SPY/QQQ/equities: **PASS**
- Additional option package required: **NO**. Current rights returned every field required by AXIS.
- SPX: **PARTIAL / isolated limitation**. `US..SPX` option chain and SPXW option snapshots work, but
  the underlying index snapshot returns `暂不支持美股指数`. AXIS therefore returns
  `SPX_PROVIDER_UNSUPPORTED` and never maps SPX to SPY.

## Actual OpenD observations

- Host/port: configured local OpenD endpoint; reachable.
- Python SDK: `10.10.7008`.
- U.S. quote right reported by OpenD: stock LV3; option LV1.
- Subscription quota after verification: 0 used / 1000 available.
- Historical K-line quota after verification: 45 used / 955 remaining.
- Rate-limit observation: option-chain API returned an explicit maximum of 10 calls per 30 seconds.
  `MoomooGexMarketDataProvider` now enforces a process-wide rolling-window limiter below that cap.
- No quota exhaustion or permission error occurred for the required equity/option fields.

## Equity evidence

- SPY and NVDA snapshots returned bid, ask, last, volume and update time.
- QQQ and XLK confirmed benchmark/sector context snapshot access.
- SPY and NVDA each returned 174 sessions for the narrow entitlement check and 378 sessions through
  the production Stock Analyst lookback.
- SPY returned 120 one-minute and 120 five-minute bars from the latest completed session.
- Production Stock Analyst passed for SPY, QQQ, NVDA, TSLA, AAPL, META, PLTR and AMD. Each produced
  378 sessions, indicators, support/resistance, POC/VA, bias, scenarios and a valid PNG.
- SPY cold Stock Analyst latency was about 13.4 seconds; immediate cache hit was 5 ms.

## Option / OPRA evidence

Test contract: SPY 2026-09-14 764C (canonical AXIS/OCC mapping verified).

- Chain: 310 contracts for the tested expiry; strike, expiration and side present.
- Snapshot: bid `2.19`, ask `2.21`, last `2.19`, volume `20,292`, OI `1,206`, IV `12.375%`,
  delta `0.535992162`, gamma `0.080164075`, update timestamp present.
- Tracking adapter: BID `2.19`, MID `2.20`, LAST `2.19`; each retained the provider timestamp.
- Contract multiplier fields are exposed by the snapshot schema.
- Order book: subscription and query succeeded; best bid/ask matched the snapshot. The Sunday test
  returned one cached level per side and blank order-book server timestamps. AXIS does not require
  depth for GEX and does not substitute request time for market time.

## GEX evidence

Moomoo option surface + Moomoo 5-minute intraday bars passed for all mandatory symbols:

| Ticker | Expirations | Usable contracts | Intraday bars | Result |
|---|---:|---:|---:|---|
| SPY | 10 | 2,541 | 78 | PASS |
| QQQ | 10 | 2,470 | 78 | PASS |
| NVDA | 10 | 452 | 78 | PASS |
| TSLA | 10 | 862 | 78 | PASS |
| AAPL | 10 | 619 | 78 | PASS |

All five produced both CALL and PUT coverage, vendor Gamma, IV, OI, actual option volume, Net GEX,
Gamma regime, Magnet/Flip where qualified, support/resistance, acceleration zones and valid PNGs.
Missing observations were not filled with synthetic zeroes.

## Safety conclusion

The currently installed entitlement satisfies the tested AXIS production requirements. No
additional data package is justified by an actual missing AXIS capability. Personal Moomoo LIVE
broker writes remain disabled and are outside this migration gate.

## Production cutover evidence

- A real foreground AXIS BOT boot completed with `MASSIVE_API_KEY` explicitly empty and Research
  disabled. Discord connected, Stripe reconciliation returned HTTP 200, and startup selected
  `moomoo` for Stock Analyst, GEX surface, GEX intraday and option tracking.
- The managed `com.axis.bot` LaunchAgent was redeployed after the gate and is running with source /
  runtime hashes matching for the bot entry point and Moomoo GEX provider.
- Real Moomoo-backed Discord cards were rendered in `🧪・卡片测试` for `/stock SPY`, `/stock NVDA`,
  `/gex SPY` and `/gex NVDA`. All four uploads succeeded.
- Discord Blueprint remained unchanged: `REUSE=33 / CREATE=0 / UPDATE=0 / BLOCK=0`.
- Massive adapters and configuration remain in the repository solely as explicit rollback paths;
  production does not automatically fall back to Massive.
