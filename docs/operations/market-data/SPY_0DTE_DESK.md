# SPY 0DTE Desk Operations

Current state: `MEMBER`; five-minute member scheduler `ENABLED`; provider `Moomoo OpenD only`.

## Formal card test

`scripts/send_spy_0dte_test_card.py` sends exactly one formal embed plus deterministic PNG to
`📍・spy-0dte`. Outside market hours it uses the latest completed session and labels the card
`历史收盘测试快照`; it must never label historical data as live. `/test-spy-0dte` remains a
TEST-only capability diagnostic and is not the member card acceptance surface.

The capability gate checks OpenD connectivity, an exact-date chain containing only real
`US.SPY...` contracts, Gamma, IV, OI, Volume, Bid/Ask, provider timestamps, SPY spot, and SPY
five-minute candles. Missing critical inputs produce a diagnostic card and no score.

## Verified provider capability

On 2026-09-13, real OpenD tests returned SPY spot, 78 complete five-minute bars for the latest
completed session (2026-09-11), 390 exact-date SPY option contracts for 2026-09-11, and 310 for
2026-09-14. Sampled contracts populated Gamma, IV, OI, Volume, Bid/Ask, and update timestamps.
The TEST capability gate passes without Massive or any proxy instrument.

## Publication schedule

The scheduler starts at 09:35 ET, uses five-minute slots through the actual session close, never
backfills missed slots, and enforces one message per session-date/slot. Every slot rebuilds the
formal card from an exact-date SPY chain and completed SPY five-minute candles. Provider or Discord
failures are logged and fail closed; they do not publish a misleading member-facing error card.

The Discord-managed Bot role cannot be edited directly. The channel therefore keeps
`@everyone.view_channel=false` while allowing only the transport bits needed by the Bot; Member,
Manager and Newcomer each retain explicit `send_messages=false`. Runtime verification must confirm
that humans are read-only and the Bot has view/send/embed/attach before every deployment.

This is market-structure research, not a trading signal. It provides no CALL/PUT setup, entry,
target, stop, or specific contract recommendation and does not constitute investment advice.
