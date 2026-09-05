# AXIS GEX Explorer — Phase 1 Specification

**Version:** GEX V6 Net Magnet / Acceleration / 5-Minute / Massive Primary / Moomoo Shadow / 2026-09-05

**Status:** TEST ONLY

This document is the current source of truth for AXIS GEX Explorer. It supersedes the earlier
boundary that limited GEX to a pure calculation engine, but only for the isolated Phase 1 test
surface described here. It does not change Analysis Fusion, Signal, Trade, Results, Membership,
Newcomer, Short-Term, Swing, LEAPS, Personal Moomoo Execution, or AXIS LAB.

## Phase 1 lock

- The only command is `/gex ticker:TICKER`; a plain ticker message never triggers GEX.
- The only authorized caller is the configured Owner.
- The only authorized channel is `🧪・card-testing`.
- Manager, Member, Newcomer, and `@everyone` cannot execute it.
- `GEX_EXPLORER_ENABLED` is the kill switch and `GEX_EXPLORER_MODE` must be `TEST`.
- `MEMBER_LOUNGE` mode is rejected by the Phase 1 startup gate.
- Do not expose GEX in `🛋️・member-lounge` until the Owner explicitly says
  `APPROVE GEX LOUNGE LAUNCH` and the separate Phase 2 gate passes.

## Input and data

- Normalize case and an optional leading `$`; `SPXW` normalizes to `SPX` for a GEX request.
- SPX must use the provider's SPX index/options symbols and must never fall back to SPY.
- Massive is the only production-selected GEX data source. The existing Massive credential and
  AXIS provider boundaries supply spot, the option surface, and genuine 5-minute underlying
  candles. Secrets remain in `.env`.
- The left chart uses Massive aggregate 5-minute bars from the latest U.S. regular session and
  never constructs or interpolates synthetic candles. Massive option-surface or minute-bar failure
  is fail-closed.
- Moomoo OpenD runs only as a background shadow candidate for 5-minute-bar comparison. Shadow data
  must never select, replace, alter, delay, or block the Massive production result. Moomoo failure
  is recorded internally and does not fail the Discord card.
- Select the latest 10 valid option expirations from a larger candidate set. Skip empty,
  incomplete, or truncated expirations. Configured minimum coverage is fail-closed.
- Near-Term means 0DTE when a valid same-day expiry exists; otherwise it means the nearest valid
  expiry and must be labeled `Near-Term Structure`.
- Market-closed results use the latest available snapshot and are labeled. Stale data is labeled
  independently and must not be presented as real-time.

## Deterministic structure

- Volume GEX per 1% underlying move is `gamma × current-day option volume × 100 × spot² × 0.01`.
- Massive `day.volume` is aggregated real option trading volume, but it does not identify buyer- or
  seller-initiated flow. The signed Call-positive / Put-negative result is therefore a structural
  estimate, not order-flow direction or observed dealer inventory.
- Sign convention is estimated dealer Call positive / Put negative. This is an explicit modeling
  assumption, not observed dealer positioning.
- Missing vendor Gamma may use Black-Scholes Gamma only when provider IV is present. Missing or zero
  current-day option volume, or both missing Gamma and IV, is skipped and never replaced with OI.
- Aggregate and Near-Term surfaces calculate Net GEX, five-level Gamma Regime, Zero Gamma,
  positive-Net-GEX magnet levels/zones, negative-Net-GEX acceleration zones, gross Call/Put Wall
  references, structural bias, and deterministic structure descriptions.
- Positive Net GEX means magnet / pin structure; negative Net GEX means acceleration structure.
  Magnet and acceleration classification is mutually exclusive at every strike. Gross Call Wall
  and Put Wall remain useful one-sided concentration references, but must never be presented as
  direct resistance or support merely because that side has large gross exposure.
- All levels must come from the normalized option surface. An LLM must never invent GEX levels.
- The response is one Chinese AXIS Discord card plus one deterministic 1800x1125 composite image:
  the left side is the real 5-minute K-line with current price and structural overlays; the right
  side is a strike-by-expiration volume-GEX heatmap.
- The composite uses a 16:10-style layout. The intraday plot is approximately 1.44:1 instead of a
  stretched wide panel, and the heatmap receives wider expiration cells. The price axis is
  candle-first and may expand only for nearby Net-GEX structure. Distant magnet or Zero Gamma
  values remain visible as full-width Chinese off-scale rails and must not flatten the candles.
  Distant negative-Net-GEX clusters remain visible as full-width purple off-scale acceleration
  bands with their actual level or range; they must never disappear merely because they are outside
  the focused candle axis.
- Every chart and Discord card uses `上方主磁吸`, `上方次磁吸`, `下方主磁吸`, `下方次磁吸`, and
  `0 Gamma · Gamma 分界`. Main magnets are the strongest positive-Net-GEX strikes on each side of
  spot. Secondary magnets are the nearest same-side positive-Net-GEX strikes that meet the
  configured relative threshold, with the nearest remaining positive-Net-GEX strike as a
  deterministic fallback. Negative-Net-GEX clusters are rendered only as acceleration zones.
- Gross `Call Wall` / `Put Wall` remain visible in the strike heatmap and Discord reference field
  as `C墙` / `P墙`; they are not drawn as K-line pressure/support rails.
- Visible labels, explanations, status text, chart headings, legends, and disclaimers are Chinese.
  AXIS, GEX, Gamma, ticker symbols, provider brands, and ET may remain as technical names.
- All magnet, boundary, wall-reference, and acceleration levels come from the normalized option surface.
  The renderer does not use an LLM or image-generation model.

## Reliability and safety

- Cache key is ticker + policy version + provider. Cache TTL is policy-controlled.
- Concurrent identical misses use single-flight; per-user cooldown and per-guild fresh-request
  limits apply.
- Audit events are `GEX_REQUESTED`, `GEX_CACHE_HIT`, `GEX_CACHE_MISS`, `GEX_GENERATED`,
  `GEX_FAILED`, and `GEX_RATE_LIMITED`, using the existing AuditLog.
- Provider, data-quality, rendering, command, and excessive-latency failures use existing
  deduplicated System Alert / Recovery behavior.
- GEX is read-only. It must never create or modify Signal, Trade, Result, Mentor, Analysis,
  Membership, tracking state, or a Moomoo order.
- No database reset, public ID reset, production-message cleanup, or trading-history mutation is
  authorized by this feature.

## Test Gate

Phase 1 requires automated tests, Ruff, compileall, database/runtime/Discord verifiers, invalid and
partial failure tests, cache/single-flight/rate-limit tests, closed-market labeling, fail-closed
Massive minute-data tests, non-blocking Moomoo shadow failure tests, PNG dimension validation, and
live Massive-primary / Moomoo-shadow cross-checks. SPX is included only when the Massive entitlement
can produce a genuine SPX spot/options surface. Phase 1 ends after its report and remains TEST ONLY.
