# SPXW 0DTE Desk Operations

Current state: `TEST`; member scheduler `DISABLED`; provider `Moomoo OpenD only`.

## Safe test

Run `/test-spxw-0dte` as the configured Owner in `🧪・卡片测试`. The response is exactly one
message containing one embed and one deterministic PNG. The same probe can be sent by the local
operator script `scripts/send_spxw_0dte_test_card.py`.

The capability gate checks OpenD connectivity, an exact-date chain containing only real
`US.SPXW...` contracts, Gamma, IV, OI, Volume, Bid/Ask, provider timestamps, SPX spot, and SPX
five-minute candles. Missing critical inputs produce a diagnostic card and no score.

## Current provider limitation

On 2026-09-13, real OpenD tests returned 488 genuine SPXW contracts for 2026-09-14 and populated
Gamma, IV, OI, Volume, Bid/Ask, and update timestamps. The same OpenD returned “暂不支持美股指数”
for both `US..SPX` snapshot and historical five-minute K lines. Therefore the normal scoring gate
is closed. AXIS does not substitute SPY, infer spot from strikes, fabricate candles, or fall back to
Massive.

## Launch safety

Do not set `SPXW_0DTE_MODE=MEMBER` or `SPXW_0DTE_SCHEDULER_ENABLED=true` before the exact Owner
approval `APPROVE SPXW 0DTE MEMBER LAUNCH` and a fresh provider gate passes during a US session.
The intended scheduler starts at 09:35 ET, uses five-minute slots through the actual session close,
never backfills missed slots, and must enforce one message per session-date/slot.

This is market-structure research, not a trading signal. It provides no CALL/PUT setup, entry,
target, stop, or specific contract recommendation and does not constitute investment advice.
