# AXIS SPXW 0DTE Desk — Current Source of Truth

Version: SPXW_0DTE_V2
Status: TEST / MEMBER SCHEDULER DISABLED

This module is a read-only SPXW same-day market-structure desk. It is not a trade signal and must
never produce option recommendations, entry, target, stop, BUY/SELL, or CALL/PUT setup language.

## Instrument identity

- The product is SPXW 0DTE only.
- Moomoo does not expose an independent SPXW underlying symbol. Its official OpenD API requires
  `US..SPX` as the chain-owner lookup key, while returned weekly contract codes are `US.SPXW...`.
- AXIS must filter the real contract root to `US.SPXW` and the expiration to the exact US session
  date. Ordinary SPX monthly contracts must not enter this module.
- Spot and five-minute candles must be the real SPX index. SPY and strike-derived proxies are
  forbidden.

## Runtime gate

- Initial command: `/test-spxw-0dte`.
- Owner only, `🧪・卡片测试` only.
- Public member channel: `📍・SPXW-0DTE`; members can view but cannot send.
- The scheduler remains disabled until the Owner sends the exact approval
  `APPROVE SPXW 0DTE MEMBER LAUNCH`.
- Any missing spot, SPX five-minute candles, SPXW chain, Greeks, freshness, or minimum coverage
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

The detailed owner specification is `AXIS_SPXW_0DTE_Desk_Codex_Spec_V2.md`. This repository copy
records the enforceable runtime decisions without secrets or provider credentials.
