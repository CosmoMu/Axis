# SPY 0DTE Desk Operations

Current state: `TEST`; member scheduler `DISABLED`; provider `Moomoo OpenD only`.

## Safe test

Run `/test-spy-0dte` as the configured Owner in `🧪・卡片测试`. The response is exactly one
message containing one embed and one deterministic PNG. The same probe can be sent by the local
operator script `scripts/send_spy_0dte_test_card.py`.

The capability gate checks OpenD connectivity, an exact-date chain containing only real
`US.SPY...` contracts, Gamma, IV, OI, Volume, Bid/Ask, provider timestamps, SPY spot, and SPY
five-minute candles. Missing critical inputs produce a diagnostic card and no score.

## Verified provider capability

On 2026-09-13, real OpenD tests returned SPY spot, 78 complete five-minute bars for the latest
completed session (2026-09-11), 390 exact-date SPY option contracts for 2026-09-11, and 310 for
2026-09-14. Sampled contracts populated Gamma, IV, OI, Volume, Bid/Ask, and update timestamps.
The TEST capability gate passes without Massive or any proxy instrument.

## Launch safety

Do not set `SPY_0DTE_MODE=MEMBER` or `SPY_0DTE_SCHEDULER_ENABLED=true` before the exact Owner
approval `APPROVE SPY 0DTE MEMBER LAUNCH` and a fresh provider gate passes during a US session.
The intended scheduler starts at 09:35 ET, uses five-minute slots through the actual session close,
never backfills missed slots, and must enforce one message per session-date/slot.

This is market-structure research, not a trading signal. It provides no CALL/PUT setup, entry,
target, stop, or specific contract recommendation and does not constitute investment advice.
