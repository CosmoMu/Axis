# AXIS GEX Explorer — Phase 1 Specification

**Version:** GEX V1 / 2026-09-04

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
- Use the existing Massive credential and AXIS provider boundary. Secrets remain in `.env`.
- Select the latest 10 valid option expirations from a larger candidate set. Skip empty,
  incomplete, or truncated expirations. Configured minimum coverage is fail-closed.
- Near-Term means 0DTE when a valid same-day expiry exists; otherwise it means the nearest valid
  expiry and must be labeled `Near-Term Structure`.
- Market-closed results use the latest available snapshot and are labeled. Stale data is labeled
  independently and must not be presented as real-time.

## Deterministic structure

- Dollar GEX per 1% underlying move is `gamma × open interest × 100 × spot² × 0.01`.
- Sign convention is estimated dealer Call positive / Put negative. This is an explicit modeling
  assumption, not observed dealer positioning.
- Missing vendor Gamma may use Black-Scholes Gamma only when provider IV is present. Missing OI or
  both Gamma and IV is skipped, never silently filled with zero.
- Aggregate and Near-Term surfaces calculate Net/Positive/Negative GEX, five-level Gamma Regime,
  Zero Gamma, GEX-based Call Wall and Put Wall, deterministic positive/negative clusters,
  structural bias, and bullish/bearish trigger/target levels.
- All levels must come from the normalized option surface. An LLM must never invent GEX levels.
- The response is one AXIS Discord card plus one deterministic mobile-first heatmap.

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
partial failure tests, cache/single-flight/rate-limit tests, closed-market labeling, and live
Massive cross-checks for SPY, QQQ, NVDA, TSLA, AAPL, plus SPX only when the provider entitlement can
produce a genuine SPX spot/options surface. Phase 1 ends after its report and remains TEST ONLY.
