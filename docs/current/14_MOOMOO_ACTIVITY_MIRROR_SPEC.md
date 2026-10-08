# AXIS Moomoo Activity Mirror — Current Specification

## Purpose

`💰・1k挑战` is a private, read-only record of the Owner's Moomoo activity. It mirrors real-account
orders, fills, current positions, and a post-close daily summary into Discord so the Owner and AXIS
  Managers can follow the challenge without operating the broker from Discord.

## Access

- Visible only to Owner, `Manager`, and `AXIS BOT`.
- `@everyone`, `Newcomer`, and `Member` are explicitly denied access.
- Owner and Manager may write; the Bot publishes compact Markdown ledger entries and paginated
  summaries without requiring expanded Discord media permissions.

## Broker boundary

- Production source: local Moomoo OpenD, the unique `FUTUCA / REAL / MARGIN` US-authorized account
  identified by the Owner as account 8070. `CASH`, `TFSA`, and `SIMULATE` are excluded.
- Account IDs are never displayed or stored raw. AXIS stores only one-way masked references.
- The mirror exposes no place, modify, cancel, unlock-trade, or risk-management operation.
- KLY, manual Moomoo actions, and other external actions are treated identically because the broker
  is the source of truth.
- The first successful reconcile establishes a silent baseline. Historical orders/fills are stored
  for the current-day summary but are not replayed as a burst of Discord notifications.

## Live events

- New submitted orders are mirrored.
- Cancelled and rejected order states are mirrored.
- Every newly observed fill is mirrored idempotently using masked account + broker fill ID.
- Partial-fill executions are fill events; order polling does not create duplicate fill cards.
- Reconciliation defaults to 30 seconds and reports failure/recovery through System Alerts.

## Daily summary

- Runs at `16:15 ET` on U.S. trading days and publishes once per session date.
- Includes per-account total assets, cash, buying power, aggregated daily executions, and current
  positions with cost/current price/unrealized P&L when supplied by Moomoo.
- Missing broker fields display `—`; AXIS does not infer or fabricate realized P&L.
- Multiple fills for the same account, symbol, and side are aggregated using a quantity-weighted
  average price for a readable close report. Raw fills remain in the database.

## Feature gate

The module is independent from Owner Personal Moomoo Execution and AXIS LAB. Enabling the mirror
does not enable broker writes, auto-follow, Model A/B, or personal risk automation.
