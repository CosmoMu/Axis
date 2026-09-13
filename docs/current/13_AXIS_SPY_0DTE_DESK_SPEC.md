# AXIS SPY 0DTE Desk — Current Source of Truth

Version: SPY_0DTE_V2
Status: TEST / MEMBER SCHEDULER DISABLED

This module is a read-only SPY same-day market-structure desk. It is not a trade signal and must
never produce option recommendations, entry, target, stop, BUY/SELL, or CALL/PUT setup language.

## Instrument identity

- The product is SPY 0DTE only.
- The Moomoo underlying and option-chain owner are both `US.SPY`.
- AXIS filters contracts to the real `US.SPY...` root and the exact US session date.
- Spot and five-minute candles must be the real SPY ETF. Index, strike-derived, cached, or
  fabricated proxies are forbidden.

## Runtime gate

- Initial command: `/test-spy-0dte`.
- Owner only, `🧪・卡片测试` only.
- Public member channel: `📍・spy-0dte`; members can view but cannot send.
- The scheduler remains disabled until the Owner sends the exact approval
  `APPROVE SPY 0DTE MEMBER LAUNCH`.
- Any missing SPY spot, five-minute candles, exact-date chain, Greeks, freshness, or minimum coverage
  causes fail-closed behavior. A normal score card must not be published.

## Deterministic score

The future normal score is bounded to -100 through +100 and uses policy-controlled weights:
0DTE GEX 30%, price structure 20%, VWAP 15%, EMA9 10%, volume 10%, momentum 10%, and key-level
position 5%. Display smoothing is 70% current raw score plus 30% prior display score. The frozen
snapshot is shared by the Discord card and image renderer.

## Mandatory disclaimer

Every normal or diagnostic card states:

> 仅用于市场分析与教育。
>
> 不构成投资建议、交易建议或买卖信号。
>
> MY RISK IS NOT YOUR RISK.

The detailed owner specification is `AXIS_SPY_0DTE_Desk_Codex_Spec_V2.md`. This repository copy
records the enforceable runtime decisions without secrets or provider credentials.
