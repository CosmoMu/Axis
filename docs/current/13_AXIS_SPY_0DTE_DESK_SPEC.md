# AXIS SPY 0DTE Desk — Current Source of Truth

Version: SPY_0DTE_V3_COSMOS_METHOD
Status: MEMBER / FIVE-MINUTE SCHEDULER ENABLED

This module is a read-only SPY same-day market-structure desk. It is not a trade signal and must
never produce option recommendations, entry, target, stop, BUY/SELL, or CALL/PUT setup language.

## Instrument identity

- The product is SPY 0DTE only.
- The Moomoo underlying and option-chain owner are both `US.SPY`.
- AXIS filters contracts to the real `US.SPY...` root and the exact US session date.
- Spot and one-minute candles must be the real SPY ETF; higher timeframes are derived deterministically.
  Index, strike-derived, cached, or
  fabricated proxies are forbidden.

## Runtime and publication

- Public member channel: `📍・spy-0dte`; members can view but cannot send.
- During a valid U.S. equity session, the Bot publishes one new formal card every five minutes,
  starting at 09:35 ET and ending at the actual session close.
- Publication is session/slot idempotent, does not backfill missed slots, and respects holidays and
  half days through `TradingCalendarService`.
- The formal Discord embed and its GEX image use the same frozen Moomoo snapshot. The first view is
  the market-structure summary, not a capability-test card.
- Any missing SPY spot, five-minute candles, exact-date chain, Greeks, freshness, or minimum coverage
  causes fail-closed behavior. A normal score card must not be published.

## Deterministic Cosmos-method score

The committed Cosmos SPX 5-minute GEX method is ported into AXIS and scaled to real listed SPY
strikes. It combines 1m/5m/15m/1h momentum at 10%/25%/35%/30%, then combines that momentum result
with Gamma-location context at 75%/25%. The output is bounded to -100 through +100 and capped by
data quality. Scenario percentages are deterministic relative priorities, never win rates.

Primary GEX is Moomoo OI-weighted 0DTE Gamma. Volume-weighted Gamma remains a secondary flow field.
The formal 1400×1500 image follows the Cosmos terminal layout: four summary panels, three intraday
scenarios, multi-timeframe momentum, prior-slot changes, and a symmetric red/green Net GEX strike
chart. All branding and instruments remain AXIS / SPY; no Cosmos runtime import or SPX proxy exists.

## Mandatory disclaimer

Every normal or diagnostic card states:

> 仅用于市场分析与教育。
>
> 不构成投资建议、交易建议或买卖信号。
>
> MY RISK IS NOT YOUR RISK.

The detailed owner specification is `AXIS_SPY_0DTE_Desk_Codex_Spec_V2.md`. This repository copy
records the enforceable runtime decisions without secrets or provider credentials.
